# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDlAppOwnerAlerts(TransactionCase):
    """Owner cash box notifications land in the DoniaLink App inbox."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        Users = cls.env['res.users'].with_context(no_reset_password=True)
        cls.manager = Users.create({'name': 'DLT Manager', 'login': 'dlt_manager',
                                    'groups_id': [(6, 0, cls.env.ref('base.group_user').ids)]})
        cls.owner_user = Users.create({'name': 'DLT Owner', 'login': 'dlt_owner',
                                       'groups_id': [(6, 0, cls.env.ref('base.group_portal').ids)]})
        cls.Kind = cls.env['donialink.app.kind']
        cls.Message = cls.env['donialink.app.message']
        for code in ('owner_statement', 'owner_card_move', 'owner_expense_duplicate'):
            cls.Kind._get(code).recipient_ids = cls.manager
        drawings = cls.env['account.account'].create({'name': 'DLT Drawings', 'code': 'DLT3100',
                                                      'account_type': 'equity'})
        cls.box = cls.env['ecc.owner.box'].create({'name': 'DLT Ali', 'drawings_account_id': drawings.id})
        cls.box2 = cls.env['ecc.owner.box'].create({'name': 'DLT Omar', 'drawings_account_id': drawings.id})

    def _messages(self, kind):
        return self.Message.search([('kind_code', '=', kind)])

    def test_kinds_exist(self):
        codes = set(self.Kind.search([]).mapped('code'))
        for code in ('owner_session_closed', 'owner_statement', 'owner_card_move', 'owner_card_sales',
                     'owner_expense_reviewed', 'owner_expense_rejected', 'owner_expense_duplicate',
                     'owner_difference_explained', 'owner_reminder_expense', 'owner_reminder_count',
                     'receipt_new', 'receipt_staff'):
            self.assertIn(code, codes)

    def test_owner_messages(self):
        self.box.app_user_id = self.owner_user
        answer, _pushed = self.box._owner_notify('statement', 'Your statement\nBalance 10', 'Your statement is ready',
                                                 body='Balance 10', route='statements', tag='statement-1')
        message = self._messages('owner_statement')
        self.assertEqual(set(message.user_id.ids), {self.owner_user.id, self.manager.id})
        self.assertEqual(set(message.mapped('title')), {'Your statement is ready'})
        mine = message.filtered(lambda m: m.user_id == self.owner_user)
        self.assertEqual(mine.url, '#cashbox/%s/statements' % self.box.id, 'a tap opens the cash box screen')
        self.assertTrue(answer.get('delivered'), 'a statement counts as sent when it reached the app')

    def test_owner_without_the_company(self):
        """The owner's login may not have the box's company: they still get their own box's messages."""
        other = self.env['res.company'].create({'name': 'DLT Other Co'})
        self.owner_user.write({'company_ids': [(6, 0, other.ids)], 'company_id': other.id})
        self.box.app_user_id = self.owner_user
        self.box._owner_notify('statement', 'x', 'Statement', route='statements')
        mine = self._messages('owner_statement').filtered(lambda m: m.user_id == self.owner_user)
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine.company_id, self.box.company_id)

    def test_duplicate_expense_has_its_kind(self):
        self.box.app_user_id = self.owner_user
        self.box._owner_notify('expense_duplicate', 'x', 'Expense is a duplicate', route='moves')
        self.assertEqual(set(self._messages('owner_expense_duplicate').user_id.ids),
                         {self.owner_user.id, self.manager.id})
        self.assertFalse(self._messages('scheduled_report').filtered(lambda m: m.title == 'Expense is a duplicate'))

    def test_one_event_once_per_person(self):
        """A card movement is told to each co-owner box: the people chosen for the kind get it once."""
        owner2 = self.owner_user.copy({'login': 'dlt_owner2'})
        self.box.app_user_id = self.owner_user
        self.box2.app_user_id = owner2
        for box in self.box | self.box2:
            box._owner_notify('card_move', 'Card: 100', 'Card: 100', body='−10 · took', route='bankcard',
                              tag='card-move-42')
        messages = self._messages('owner_card_move')
        self.assertEqual(sorted(messages.user_id.ids), sorted([self.manager.id, self.owner_user.id, owner2.id]))
        # another event of the same kind is not held back
        self.box._owner_notify('card_move', 'Card: 90', 'Card: 90', route='bankcard', tag='card-move-43')
        self.assertEqual(len(self._messages('owner_card_move')), 5)

    def test_no_platform_left(self):
        """Owner messages go to the DoniaLink App only: nothing is posted to the DoniaLink Platform."""
        Box = type(self.box)
        self.assertFalse(hasattr(Box, '_platform_send'))
        self.assertFalse(hasattr(Box, 'action_generate_link'))
        self.assertFalse(hasattr(type(self.env['telegram.service']), 'donialink_post'))
        self.box.write({'telegram_user_id': '777', 'platform_enabled': True})
        answer, pushed = self.box._owner_notify('statement', 'x', 'Statement', route='statements')
        self.assertEqual(pushed, 0, 'no app login: no phone of the owner')
        self.assertEqual(self._messages('owner_statement').user_id, self.manager,
                         'only the people chosen for the kind, in the app')
        self.assertFalse(answer.get('delivered'), 'not "delivered": the owner did not get it')
