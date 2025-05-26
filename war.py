"""
war card game client and server
"""
import asyncio
from collections import namedtuple
from enum import Enum
import logging
import random
import socket
import socketserver
import threading
import sys


"""
Namedtuples work like classes, but are much more lightweight so they end
up being faster. It would be a good idea to keep objects in each of these
for each game which contain the game's state, for instance things like the
socket, the cards given, the cards still available, etc.
"""
Game = namedtuple("Game", ["p1", "p2"])

# Stores the clients waiting to get connected to other clients
waiting_clients = []


class Command(Enum):
    """
    The byte values sent as the first byte of any message in the war protocol.
    """
    WANTGAME = 0
    GAMESTART = 1
    PLAYCARD = 2
    PLAYRESULT = 3


class Result(Enum):
    """
    The byte values sent as the payload byte of a PLAYRESULT message.
    """
    WIN = 0
    DRAW = 1
    LOSE = 2

def readexactly(sock, numbytes):
    """
    Accumulate exactly `numbytes` from `sock` and return those. If EOF is found
    before numbytes have been received, be sure to account for that here or in
    the caller.
    """
    buf = b""
    while len(buf) < numbytes:
        chunk = sock.recv(numbytes - len(buf))
        if not chunk:
            # EOF: connection closed
            break
        buf += chunk
    return buf


def kill_game(game):
    """
    If either client sends a bad message, immediately nuke the game.
    """
    try:
        game.p1.close()
    except Exception:
        pass
    try:
        game.p2.close()
    except Exception:
        pass
    logging.error("Game killed due to bad message.")
    


def compare_cards(card1, card2):
    """
    Given an integer card representation, return -1 for card1 < card2,
    0 for card1 = card2, and 1 for card1 > card2
    """
    card1val= card1%13 #ignoring suits
    card2val= card2%13
    if card1val<card2val:
        return -1
    elif card1val==card2val:
        return 0
    else:
        return 1
    
    

def deal_cards():
    """
    Randomize a deck of cards (list of ints 0..51), and return two
    26 card "hands."
    """
    deck = list(range(52))  # Cards 0 through 51
    random.shuffle(deck)
    return (deck[:26], deck[26:])

def send_message(sock, command, data):
    """
    Send a message consisting of the command byte and data to the given socket.
    """
    message = bytes([command]) + data
    sock.sendall(message)


def start_game(sock1, sock2, hand1, hand2):
    """
    Start the game: send game start command to both clients.
    """
    send_message(sock1, Command.GAMESTART.value, bytes(hand1))
    send_message(sock2, Command.GAMESTART.value, bytes(hand2))
    logging.info("Game started between clients.")


def play_round(sock1, sock2, card1, card2):
    """
    Play a round where both clients play one card each.
    Compare the cards, and send back the result to both clients.
    """
    result = compare_cards(card1, card2)
    
    if result == 1:
        send_message(sock1, Command.PLAYRESULT.value, bytes([Result.WIN.value]))
        send_message(sock2, Command.PLAYRESULT.value, bytes([Result.LOSE.value]))
    elif result == -1:
        send_message(sock1, Command.PLAYRESULT.value, bytes([Result.LOSE.value]))
        send_message(sock2, Command.PLAYRESULT.value, bytes([Result.WIN.value]))
    else:
        send_message(sock1, Command.PLAYRESULT.value, bytes([Result.DRAW.value]))
        send_message(sock2, Command.PLAYRESULT.value, bytes([Result.DRAW.value]))


def handle_game(sock1, sock2):
    """
    Handle the game protocol between two connected clients. This function runs the game.
    """
    try:
        # Deal cards
        hand1, hand2 = deal_cards()

        # Start the game
        start_game(sock1, sock2, hand1, hand2)

        # Initialize scores
        score1 = 0
        score2 = 0

        # Play the game rounds
        for _ in range(26):
            # Wait for responses (the played cards)
            msg1 = readexactly(sock1, 2)
            msg2 = readexactly(sock2, 2)

            if (msg1[0] < 0) or (msg1[0] >3) or (msg2[0] < 0) or (msg2[0] >3) :
                kill_game(Game(sock1, sock2))
                return

            card1 = msg1[1]
            card2 = msg2[1]

            # Handle the result of the round
            result = compare_cards(card1, card2)
            if result == 1:
                score1 += 1
            elif result == -1:
                score2 += 1

            play_round(sock1, sock2, card1, card2)

        # Declare the winner
        if score1 > score2:
            logging.info("Player 1 wins the game!")
        elif score2 > score1:
            logging.info("Player 2 wins the game!")
        else:
            logging.info("The game is a draw.")

    except Exception as e:
        logging.error(f"Error during game: {e}")
    finally:
        sock1.close()
        sock2.close()


def serve_game(host, port):
    """
    Open a socket for listening for new connections on host:port, and
    perform the war protocol to serve a game of war between each client.
    This function should run forever, continually serving clients.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_sock:
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind((host, port))
        server_sock.listen()
        logging.info(f"Server listening on {host}:{port}")

        while True:
            # Accept new client connections
            client_sock, addr = server_sock.accept()
            logging.debug(f"Client connected from {addr}")
            waiting_clients.append(client_sock)

            # When two clients are available, start a game
            if len(waiting_clients) >= 2:
                # Pop two clients for the game
                p1 = waiting_clients.pop(0)
                p2 = waiting_clients.pop(0)

                # Start the game in a separate thread
                threading.Thread(target=handle_game, args=(p1, p2), daemon=True).start()




async def limit_client(host, port, loop, sem):
    """
    Limit the number of clients currently executing.
    You do not need to change this function.
    """
    async with sem:
        return await client(host, port, loop)

async def client(host, port, loop):
    """
    Run an individual client on a given event loop.
    You do not need to change this function.
    """
    try:
        reader, writer = await asyncio.open_connection(host, port)
        # send want game
        writer.write(b"\0\0")
        card_msg = await reader.readexactly(27)
        myscore = 0
        for card in card_msg[1:]:
            writer.write(bytes([Command.PLAYCARD.value, card]))
            result = await reader.readexactly(2)
            if result[1] == Result.WIN.value:
                myscore += 1
            elif result[1] == Result.LOSE.value:
                myscore -= 1
        if myscore > 0:
            result = "won"
        elif myscore < 0:
            result = "lost"
        else:
            result = "drew"
        logging.debug("Game complete, I %s", result)
        writer.close()
        return 1
    except ConnectionResetError:
        logging.error("ConnectionResetError")
        return 0
    except asyncio.streams.IncompleteReadError:
        logging.error("asyncio.streams.IncompleteReadError")
        return 0
    except OSError:
        logging.error("OSError")
        return 0

def main(args):
    """
    launch a client/server
    """
    host = args[1]
    port = int(args[2])
    if args[0] == "server":
        try:
            # your server should serve clients until the user presses ctrl+c
            serve_game(host, port)
        except KeyboardInterrupt:
            pass
        return
    else:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
        
        asyncio.set_event_loop(loop)
        
    if args[0] == "client":
        loop.run_until_complete(client(host, port, loop))
    elif args[0] == "clients":
        sem = asyncio.Semaphore(1000)
        num_clients = int(args[3])
        clients = [limit_client(host, port, loop, sem)
                   for x in range(num_clients)]
        async def run_all_clients():
            """
            use `as_completed` to spawn all clients simultaneously
            and collect their results in arbitrary order.
            """
            completed_clients = 0
            for client_result in asyncio.as_completed(clients):
                completed_clients += await client_result
            return completed_clients
        res = loop.run_until_complete(
            asyncio.Task(run_all_clients(), loop=loop))
        logging.info("%d completed clients", res)

    loop.close()

if __name__ == "__main__":
    # Changing logging to DEBUG
    logging.basicConfig(level=logging.DEBUG)
    main(sys.argv[1:])
