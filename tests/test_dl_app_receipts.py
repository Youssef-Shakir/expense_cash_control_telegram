# -*- coding: utf-8 -*-
import base64
import json

from odoo.tests import HttpCase, new_test_user, tagged

# a 1x1 JPEG
JPEG = base64.b64decode(
    '/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////'
    '////////////////////2wBDAf//////////////////////////////////////////////////////////////////////////'
    '////////////wAARCAABAAEDASIAAhEBAxEB/8QAFAABAAAAAAAAAAAAAAAAAAAAA//EABQQAQAAAAAAAAAAAAAAAAAAAAD/xAAUAQEA'
    'AAAAAAAAAAAAAAAAAAAA/8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEQMRAD8AP//Z')


@tagged('post_install', '-at_install')
class TestAppReceipts(HttpCase):

    def setUp(self):
        super().setUp()
        self.cashier = new_test_user(self.env, 'dl_rc_cashier', password='dl_rc_cashier1',
                                     groups='base.group_portal,expense_cash_control_telegram.group_receipt_sender')
        self.nobody = new_test_user(self.env, 'dl_rc_nobody', password='dl_rc_nobody1', groups='base.group_user')
        self.accountant = new_test_user(self.env, 'dl_rc_acc', password='dl_rc_acc1',
                                        groups='base.group_user,expense_cash_control.group_expense_manager')
        self.env.ref('expense_cash_control_telegram.kind_receipt_new').recipient_ids = self.accountant
        self.Message = self.env['donialink.app.message']

    def api(self, action, **params):
        response = self.url_open('/dl/app/receipts/api/%s' % action, data=json.dumps({'params': params}),
                                 headers={'Content-Type': 'application/json'})
        self.assertEqual(response.status_code, 200)
        return response.json()['result']

    def photo(self):
        return {'content_b64': base64.b64encode(JPEG).decode(), 'mimetype': 'image/jpeg', 'filename': 'bill.jpg'}

    def test_send_from_app(self):
        self.authenticate('dl_rc_cashier', 'dl_rc_cashier1')
        result = self.api('send', photos=[self.photo(), self.photo()], paid_by='cashier', amount='25000',
                          note='gas cylinder')
        receipt = self.env['ecc.receipt'].browse(result['id'])
        self.assertEqual(receipt.app_user_id, self.cashier)
        self.assertEqual(receipt.paid_by, 'cashier')
        self.assertEqual(receipt.amount, 25000)
        self.assertEqual(len(receipt.photo_ids), 2)
        self.assertEqual(receipt.state, 'to_review')
        notified = self.Message.search([('kind_code', '=', 'receipt_new')])
        self.assertEqual(notified.user_id, self.accountant)
        self.assertEqual(notified.url, '/odoo/ecc.receipt/%s' % receipt.id)
        mine = self.api('mine')['receipts']
        self.assertEqual([r['id'] for r in mine], [receipt.id])
        # the photo is served to the sender only
        photo = receipt.photo_ids[0]
        self.assertEqual(self.url_open('/dl/app/receipts/photo/%s' % photo.id).status_code, 200)
        self.authenticate('dl_rc_nobody', 'dl_rc_nobody1')
        self.assertEqual(self.url_open('/dl/app/receipts/photo/%s' % photo.id).status_code, 404)
        self.assertEqual(self.api('receipt', receipt_id=receipt.id)['error'], 'user')

    def test_send_needs_group_and_photo(self):
        self.authenticate('dl_rc_nobody', 'dl_rc_nobody1')
        self.assertEqual(self.api('send', photos=[self.photo()], paid_by='cashier')['error'], 'user')
        self.authenticate('dl_rc_cashier', 'dl_rc_cashier1')
        self.assertEqual(self.api('send', photos=[], paid_by='cashier')['error'], 'user')
        self.assertEqual(self.api('send', photos=[{'content_b64': 'not base64!'}], paid_by='cashier')['error'], 'user')
        self.assertFalse(self.env['ecc.receipt'].search([('app_user_id', '=', self.cashier.id)]))

    def test_question_answer_and_review(self):
        receipt = self.env['ecc.receipt']._app_create(self.cashier, [self.photo()], paid_by='payable', note='flour')
        # the accountant asks: it goes to the sender's app, not Telegram
        action = receipt.with_user(self.accountant).action_ask_question()
        wizard = self.env['ecc.receipt.question.wizard'].with_user(self.accountant).with_context(
            action['context']).create({'text': 'Which vendor?'})
        wizard.action_send()
        question = receipt.question_ids
        self.assertEqual(question.state, 'sent')
        asked = self.Message.search([('user_id', '=', self.cashier.id), ('kind_code', '=', 'receipt_staff')])
        self.assertEqual(asked.url, '#receipt/%s' % receipt.id)
        self.assertEqual(self.env['ecc.receipt'].with_user(self.cashier).dl_app_open_questions(), 1)
        # the sender answers in the app
        self.authenticate('dl_rc_cashier', 'dl_rc_cashier1')
        result = self.api('answer', receipt_id=receipt.id, question_id=question.id, text='Al-Noor bakery')
        self.assertEqual(result['questions'][0]['answer'], 'Al-Noor bakery')
        self.assertEqual(question.state, 'answered')
        self.assertEqual(self.env['ecc.receipt'].with_user(self.cashier).dl_app_open_questions(), 0)
        self.assertTrue(self.Message.search([('user_id', '=', self.accountant.id), ('title', 'ilike', 'Answer')]))
        # rejected: the sender is told
        receipt.with_user(self.accountant).action_reject()
        self.assertTrue(self.Message.search([('user_id', '=', self.cashier.id), ('title', 'ilike', 'rejected')]))

    def test_tile_for_senders_only(self):
        self.authenticate('dl_rc_cashier', 'dl_rc_cashier1')
        keys = [s['key'] for s in self.url_open('/dl/app/api/session', data=json.dumps({'params': {}}),
                headers={'Content-Type': 'application/json'}).json()['result']['screens']]
        self.assertIn('receipt', keys)
        self.authenticate('dl_rc_nobody', 'dl_rc_nobody1')
        keys = [s['key'] for s in self.url_open('/dl/app/api/session', data=json.dumps({'params': {}}),
                headers={'Content-Type': 'application/json'}).json()['result']['screens']]
        self.assertNotIn('receipt', keys)
