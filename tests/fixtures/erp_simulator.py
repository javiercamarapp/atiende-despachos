# -*- coding: utf-8 -*-
"""erp_simulator.py — Minimal ERP web app for E2E testing of Computer Use.

Simulates: login form, dashboard, invoice grid, invoice registration, session expiry.
"""
from http.server import HTTPServer, SimpleHTTPRequestHandler
import json
import os
import threading
import time
from urllib.parse import parse_qs, urlparse

class ERPHandler(SimpleHTTPRequestHandler):
    SESSIONS = {}
    INVOICES = []
    
    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/':
            self._serve_login()
        elif path == '/dashboard':
            self._check_session(self._serve_dashboard)
        elif path == '/facturas':
            self._check_session(self._serve_facturas)
        elif path == '/api/invoices':
            self._check_session(self._serve_api_invoices)
        else:
            self.send_error(404)
    
    def do_POST(self):
        path = urlparse(self.path).path
        if path == '/login':
            self._handle_login()
        elif path == '/facturas/registrar':
            self._check_session(self._handle_register)
        else:
            self.send_error(404)
    
    def _serve_login(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(b'''
        <html><head><title>ERP Login</title></head><body>
        <h1 id="login-title">Iniciar Sesion</h1>
        <form method="POST" action="/login">
            <input type="text" name="username" id="username" placeholder="Usuario">
            <input type="password" name="password" id="password" placeholder="Password">
            <button type="submit" id="login-submit">Entrar</button>
        </form>
        </body></html>
        ''')
    
    def _handle_login(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode()
        params = parse_qs(body)
        username = params.get('username', [''])[0]
        password = params.get('password', [''])[0]
        
        if username == 'admin' and password == 'correct':
            token = f'session_{len(self.SESSIONS)+1}_{int(time.time())}'
            self.SESSIONS[token] = {'user': username, 'created': time.time()}
            self.send_response(302)
            self.send_header('Set-Cookie', f'session={token}; Path=/')
            self.send_header('Location', '/dashboard')
            self.end_headers()
        else:
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<html><body><h1 id="login-title">Iniciar Sesion</h1><p id="error">Credenciales incorrectas</p></body></html>')
    
    def _check_session(self, handler):
        cookie = self.headers.get('Cookie', '')
        token = None
        for part in cookie.split(';'):
            part = part.strip()
            if part.startswith('session='):
                token = part[8:]
        if token and token in self.SESSIONS:
            handler()
        else:
            self.send_response(302)
            self.send_header('Location', '/')
            self.end_headers()
    
    def _serve_dashboard(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(b'<html><body><h1 id="dashboard-title">Dashboard</h1><nav id="main-nav"><a href="/facturas">Facturas</a></nav></body></html>')
    
    def _serve_facturas(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        rows = ''
        for inv in self.INVOICES:
            rows += f'<tr><td>{inv["folio"]}</td><td>{inv["emisor"]}</td><td>{inv["total"]}</td><td>{inv["status"]}</td></tr>'
        self.wfile.write(f'''
        <html><body>
        <h1 id="facturas-title">Facturas</h1>
        <table id="invoice-grid">
        <thead><tr><th>Folio</th><th>Emisor</th><th>Total</th><th>Status</th></tr></thead>
        <tbody>{rows}</tbody>
        </table>
        <form method="POST" action="/facturas/registrar">
            <input type="text" name="folio" id="folio-input" placeholder="Folio">
            <input type="text" name="emisor" id="emisor-input" placeholder="Emisor">
            <input type="text" name="total" id="total-input" placeholder="Total">
            <button type="submit" id="register-submit">Registrar</button>
        </form>
        </body></html>
        '''.encode())
    
    def _handle_register(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode()
        params = parse_qs(body)
        invoice = {
            'folio': params.get('folio', [''])[0],
            'emisor': params.get('emisor', [''])[0],
            'total': params.get('total', [''])[0],
            'status': 'registrada',
        }
        self.INVOICES.append(invoice)
        self.send_response(302)
        self.send_header('Location', '/facturas')
        self.end_headers()
    
    def _serve_api_invoices(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(self.INVOICES).encode())
    
    def log_message(self, format, *args):
        pass  # Suppress logs during tests


def start_erp_server(port=18765):
    server = HTTPServer(('127.0.0.1', port), ERPHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
