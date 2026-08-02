# -*- coding: utf-8 -*-
"""test_computer_use_e2e.py — E2E tests for Computer Use with REAL Chromium.

These tests launch a real Chromium browser against a local ERP fixture.
No mocks. No Playwright fakes.
"""
import pytest
import asyncio
import sys
import os

# Mark all tests in this module
pytestmark = pytest.mark.computer_use_e2e

@pytest.fixture(scope='module')
def erp_fixture():
    """Start local ERP fixture server."""
    from tests.fixtures.erp_simulator import start_erp_server, ERPHandler
    ERPHandler.INVOICES = []  # Reset
    ERPHandler.SESSIONS = {}  # Reset
    server = start_erp_server(port=18765)
    yield 'http://127.0.0.1:18765'
    server.shutdown()

@pytest.fixture
def playwright_desktop():
    from b2b_ai.computer_use.playwright_desktop import PlaywrightDesktop
    desktop = PlaywrightDesktop(headless=True)
    yield desktop
    # Cleanup handled by test

# --- REAL TESTS WITH CHROMIUM ---

class TestComputerUseE2E:
    """Tests that open real Chromium against the ERP fixture."""
    
    def test_import_playwright(self):
        from playwright.async_api import async_playwright
        assert async_playwright is not None
    
    def test_launch_and_close_browser(self, erp_fixture):
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(erp_fixture)
        assert 'Login' in page.title() or 'ERP' in page.title()
        browser.close()
        pw.stop()
    
    def test_login_wrong_password_shows_error(self, erp_fixture):
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(erp_fixture)
        page.fill('#username', 'admin')
        page.fill('#password', 'wrong')
        page.click('#login-submit')
        page.wait_for_load_state('networkidle')
        error = page.query_selector('#error')
        assert error is not None, 'Wrong password must show error element'
        assert 'incorrecta' in error.text_content().lower() or 'error' in error.text_content().lower()
        browser.close()
        pw.stop()
    
    def test_login_correct_navigates_to_dashboard(self, erp_fixture):
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(erp_fixture)
        page.fill('#username', 'admin')
        page.fill('#password', 'correct')
        page.click('#login-submit')
        page.wait_for_load_state('networkidle')
        assert '/dashboard' in page.url
        title = page.query_selector('#dashboard-title')
        assert title is not None, 'Dashboard must have title element'
        assert 'Dashboard' in title.text_content()
        browser.close()
        pw.stop()
    
    def test_navigate_to_facturas(self, erp_fixture):
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(erp_fixture)
        page.fill('#username', 'admin')
        page.fill('#password', 'correct')
        page.click('#login-submit')
        page.wait_for_load_state('networkidle')
        page.click('a[href="/facturas"]')
        page.wait_for_load_state('networkidle')
        title = page.query_selector('#facturas-title')
        assert title is not None, 'Facturas page must have title'
        assert 'Factura' in title.text_content()
        browser.close()
        pw.stop()
    
    def test_register_invoice_appears_in_grid(self, erp_fixture):
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(erp_fixture)
        page.fill('#username', 'admin')
        page.fill('#password', 'correct')
        page.click('#login-submit')
        page.wait_for_load_state('networkidle')
        page.click('a[href="/facturas"]')
        page.wait_for_load_state('networkidle')
        page.fill('#folio-input', 'TEST-001')
        page.fill('#emisor-input', 'Empresa Test SA')
        page.fill('#total-input', '15000.00')
        page.click('#register-submit')
        page.wait_for_load_state('networkidle')
        grid = page.query_selector('#invoice-grid')
        assert grid is not None
        content = grid.text_content()
        assert 'TEST-001' in content, 'Registered invoice must appear in grid'
        assert 'Empresa Test' in content
        browser.close()
        pw.stop()
    
    def test_session_required_for_protected_routes(self, erp_fixture):
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(erp_fixture + '/dashboard')
        page.wait_for_load_state('networkidle')
        assert '/dashboard' not in page.url or 'Login' in page.title() or 'login' in page.content().lower()
        browser.close()
        pw.stop()
    
    def test_unauthorized_access_redirects_to_login(self, erp_fixture):
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(erp_fixture + '/facturas')
        page.wait_for_load_state('networkidle')
        # Should redirect to login
        assert page.url.endswith('/') or 'Login' in page.title() or 'login' in page.content().lower()
        browser.close()
        pw.stop()
