#!/usr/bin/env python3
"""
WAN NAT Router Emulator for TrustFL Scenario 3.
Emulates 3 separate NAT routers on 3 distinct subnets/IPs:
- Site A (Hospital A): Gateway on 127.0.0.1:9001 -> NAT WAN IP 127.0.0.10
- Site B (Hospital B): Gateway on 127.0.0.1:9002 -> NAT WAN IP 127.0.0.11
- Site C (Factory C):  Gateway on 127.0.0.1:9003 -> NAT WAN IP 127.0.0.12

All traffic forwarded to the Cloud Coordinator TLS port (default: 8443).
Inbound connections from the Cloud to the Edge sites are blocked (outbound-only).
"""

from __future__ import annotations

import argparse
import logging
import select
import socket
import sys
import threading
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s [NAT] %(message)s",
)
logger = logging.getLogger("wan_nat")


class NatGateway:
    def __init__(
        self,
        name: str,
        listen_port: int,
        wan_ip: str,
        target_host: str = "127.0.0.1",
        target_port: int = 8443,
    ) -> None:
        self.name = name
        self.listen_port = listen_port
        self.wan_ip = wan_ip
        self.target_host = target_host
        self.target_port = target_port
        self.active = True
        self.server_sock: socket.socket | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind(("127.0.0.1", self.listen_port))
        self.server_sock.listen(50)
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        logger.info(
            "%s started: private gateway 127.0.0.1:%d -> WAN IP %s -> %s:%d",
            self.name,
            self.listen_port,
            self.wan_ip,
            self.target_host,
            self.target_port,
        )

    def _listen_loop(self) -> None:
        while self.active and self.server_sock:
            try:
                client_sock, client_addr = self.server_sock.accept()
                threading.Thread(
                    target=self._handle_client, args=(client_sock,), daemon=True
                ).start()
            except Exception:
                break

    def _handle_client(self, client_sock: socket.socket) -> None:
        try:
            req = client_sock.recv(4096)
            if not req:
                client_sock.close()
                return

            # Connect outbound using WAN NAT IP
            out_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            out_sock.bind((self.wan_ip, 0))
            out_sock.connect((self.target_host, self.target_port))

            # If HTTP CONNECT tunnel
            if req.startswith(b"CONNECT"):
                client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            else:
                out_sock.sendall(req)

            self._pipe_bidirectional(client_sock, out_sock)
        except Exception as e:
            logger.debug("[%s] Connection error: %s", self.name, e)
            try:
                client_sock.close()
            except Exception:
                pass

    def _pipe_bidirectional(self, s1: socket.socket, s2: socket.socket) -> None:
        def pipe(src: socket.socket, dst: socket.socket) -> None:
            try:
                while self.active:
                    data = src.recv(8192)
                    if not data:
                        break
                    dst.sendall(data)
            except Exception:
                pass
            finally:
                try:
                    src.close()
                except Exception:
                    pass
                try:
                    dst.close()
                except Exception:
                    pass

        t1 = threading.Thread(target=pipe, args=(s1, s2), daemon=True)
        t2 = threading.Thread(target=pipe, args=(s2, s1), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    def stop(self) -> None:
        self.active = False
        if self.server_sock:
            try:
                self.server_sock.close()
            except Exception:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="TrustFL WAN NAT Emulator")
    parser.add_argument("--target-port", type=int, default=8443, help="NGINX TLS target port")
    args = parser.parse_args()

    gateways = [
        NatGateway("Hospital A (Site 1)", 9001, "127.0.0.10", target_port=args.target_port),
        NatGateway("Hospital B (Site 2)", 9002, "127.0.0.11", target_port=args.target_port),
        NatGateway("Factory C  (Site 3)", 9003, "127.0.0.12", target_port=args.target_port),
    ]

    for gw in gateways:
        gw.start()

    logger.info("WAN NAT Emulator is running. Press CTRL+C to terminate.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping gateways...")
        for gw in gateways:
            gw.stop()


if __name__ == "__main__":
    main()

