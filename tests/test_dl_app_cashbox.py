# -*- coding: utf-8 -*-
import json
from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.tests import HttpCase, new_test_user, tagged


@tagged('post_install', '-at_install')
class TestDlAppCashbox(HttpCase):
    """The owner cash box inside the DoniaLink App (/dl/app#cashbox), on the owner app's API."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        env = cls.env
        Account = env['account.account']
        cls.drawings = Account.create({'name': 'DLC Drawings', 'code': 'DLC310', 'account_type': 'equity'})
        expense = Account.create({'name': 'DLC Expense', 'code': 'DLC601', 'account_type': 'expense'})
        cls.category = env['expense.category'].create({
            'name': 'DLC Gas', 'code': 'DLC-GAS', 'account_id': expense.id, 'owner_expense': True})
        cls.box = env['ecc.owner.box'].create({
            'name': 'DLC Ali', 'drawings_account_id': cls.drawings.id,
            'collect_from': fields.Date.today() - timedelta(days=1)})
        cls.other_box = env['ecc.owner.box'].create({'name': 'DLC Omar', 'drawings_account_id': cls.drawings.id})
        wizard = env['ecc.owner.app.access'].with_context(ecc_owner_box_id=cls.box.id).create({
            'mode': 'new', 'login': 'dlc_owner', 'password': 'dlc-owner-pass-1'})
        wizard.action_confirm()
        cls.owner_user = cls.box.app_user_id
        cls.staff = new_test_user(env, 'dlc_staff', password='dlc-staff-pass-1', groups='base.group_user')

    def _json(self, url, **params):
        response = self.url_open(url, data=json.dumps({'jsonrpc': '2.0', 'method': 'call', 'params': params, 'id': 1}),
                                 headers={'Content-Type': 'application/json'}, timeout=60)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertNotIn('error', body, body.get('error'))
        return body['result']

    def api(self, action, **params):
        return self._json('/dl/app/cashbox/api/%s' % action, **params)

    def screens(self):
        return [s['key'] for s in self._json('/dl/app/api/session')['screens']]

    # ------------------------------------------------------------------

    def test_tile_only_for_owners(self):
        self.authenticate('dlc_owner', 'dlc-owner-pass-1')
        self.assertIn('cashbox', self.screens())
        badges = self._json('/dl/app/api/badges')['badges']
        self.assertIn('cashbox', badges)
        self.authenticate('dlc_staff', 'dlc-staff-pass-1')
        self.assertNotIn('cashbox', self.screens())
        self.assertNotIn('cashbox', self._json('/dl/app/api/badges')['badges'])

    def test_api_own_box_only(self):
        self.authenticate('dlc_owner', 'dlc-owner-pass-1')
        info = self.api('session')
        self.assertEqual([b['box_id'] for b in info['boxes']], [self.box.id])
        home = self.api('home', box_id=self.box.id)
        self.assertEqual(home['card']['box_id'], self.box.id)
        self.assertEqual(self.api('home', box_id=self.other_box.id)['error'], 'forbidden')
        self.assertEqual(self.api('took', box_id=self.other_box.id, amount=10, request_uid='x1')['error'], 'forbidden')
        # login, logout and the phone's push belong to the DoniaLink App itself
        for action in ('login', 'logout', 'push_subscribe', '_box'):
            self.assertEqual(self.api(action)['error'], 'not_found')

        # a write, same request id twice: recorded once
        first = self.api('took', box_id=self.box.id, amount=5000, note='lunch', request_uid='dlc-took-1')
        self.assertTrue(first['ok'])
        again = self.api('took', box_id=self.box.id, amount=5000, note='lunch', request_uid='dlc-took-1')
        self.assertTrue(again.get('replayed'))
        moves = self.api('moves', box_id=self.box.id)['moves']
        self.assertEqual(len([m for m in moves if m['type'] == 'drawing']), 1)
        self.assertEqual(self.api('categories', box_id=self.box.id)['categories'][0]['id'], self.category.id)
        refused = self.api('expense', box_id=self.box.id, amount=0, category_id=self.category.id, request_uid='e0')
        self.assertTrue(refused.get('error') and refused.get('message'), 'a refusal reads {error, message}')

        # someone with no box
        self.authenticate('dlc_staff', 'dlc-staff-pass-1')
        self.assertEqual(self.api('session')['boxes'], [])
        self.assertEqual(self.api('home', box_id=self.box.id)['error'], 'forbidden')

    def test_api_needs_login(self):
        response = self.url_open('/dl/app/cashbox/api/home', data=json.dumps({'params': {'box_id': self.box.id}}),
                                 headers={'Content-Type': 'application/json'})
        self.assertIn('error', response.json(), 'auth="user": no answer for the public user')

    def test_old_address_redirects(self):
        response = self.url_open('/ecc/owner/app', allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        self.assertTrue(response.headers['Location'].endswith('/dl/app#cashbox'))
        response = self.url_open('/ecc/owner/app?box=%s&card=7' % self.box.id, allow_redirects=False)
        self.assertTrue(response.headers['Location'].endswith('/dl/app#cashbox/%s/card/7' % self.box.id))
        # the old API still answers
        self.assertFalse(self._json('/ecc/owner/api/session')['logged'])

    def test_notification_addresses(self):
        box = self.box
        self.assertEqual(box._app_url('statements'), '/dl/app#cashbox/%s/statements' % box.id)
        self.assertEqual(box._app_url(), '/dl/app#cashbox/%s' % box.id)
        self.assertEqual(box._dl_app_hash('bankcard', card=12), '#cashbox/%s/card/12' % box.id)
        self.assertEqual(box._dl_app_hash('cardwithdraw', card=12), '#cashbox/%s/card/12/withdraw' % box.id)
        self.assertEqual(box._dl_app_hash('bankcard'), '#cashbox/%s' % box.id, 'no card: the cash box')
        self.assertEqual(box._dl_app_hash('unknown'), '#cashbox/%s' % box.id)

    def test_bundle_has_the_screens(self):
        """Without running JavaScript: the app bundle carries the cash box and receipt screens."""
        paths = [path for path, *_rest in self.env['ir.asset']._get_asset_paths('donialink_app.assets_app', {})]
        for name in ('cashbox_screen.js', 'cashbox_screen.css', 'receipt_screen.js', 'receipt_screen.css'):
            self.assertIn('/expense_cash_control_telegram/static/dl_app/%s' % name, paths)
        core = paths.index('/donialink_app/static/src/app/core.js')
        self.assertGreater(paths.index('/expense_cash_control_telegram/static/dl_app/cashbox_screen.js'), core)
        page = self.url_open('/dl/app/sw.js')
        self.assertEqual(page.status_code, 200)
        # the plain JS files are not Odoo modules: they must say so on their first line
        for name in ('cashbox_screen.js', 'receipt_screen.js'):
            with open(self._static_path(name), encoding='utf-8') as file:
                self.assertEqual(file.readline().strip(), '/** @odoo-module ignore **/')

    def _static_path(self, name):
        from odoo.modules.module import get_module_path
        return '%s/static/dl_app/%s' % (get_module_path('expense_cash_control_telegram'), name)
