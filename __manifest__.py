# -*- coding: utf-8 -*-
{
    'name': 'Expenses & Cash Control - Telegram Receipts',
    'version': '18.0.4.7.0',
    'category': 'Accounting/Expenses',
    'summary': 'Staff send bill photos to the DoniaLink Telegram bot; the accountant reviews them in Odoo',
    'description': """
Telegram Receipt Capture | استلام الفواتير عبر تيليجرام
=======================================================================

Receipts: staff send bill photos from the DoniaLink App ("Send receipt"), and
receipts that came from Telegram groups through the former DoniaLink Platform bot
stay in the same inbox. The accountant reviews every receipt in one place:

* Payable  -> create a purchase order (RFQ) prefilled with the vendor and the photo;
  a "To Pay Later" expense stays available for service costs
* Cashier  -> match it to the POS cash-out it proves (never a second expense)
* Ask the sender a question: it goes to the sender's app, the answer comes
  back in the receipt chatter
* Reject / mark duplicate (photos already received are flagged)

Owner cash box: each owner / partner collects the cash of closed POS sessions,
records expenses, "took for me" and deposits; the balance is computed by Odoo,
weekly or monthly statements to confirm, differences explained by the accountant.

The owner uses the "Cash box" screen of the DoniaLink App (/dl/app#cashbox; the
old /ecc/owner/app redirects there): balance, collect sessions, expenses with
photos, took for me, deposits, count my cash, history, statements and cards.
The accountant gives access with "Owner App Access" (a free portal login);
only people linked to a box see the tile. Owner notifications land in the app
(inbox and phone), and for the people chosen per kind in DoniaLink App > Kinds.

Receipts from the DoniaLink App: a "Send receipt" screen for the group
"Can Send Receipts"; the accountant's questions go to the sender's app.

Card boxes: the bank account the card terminal pays into, shared by chosen
owners. Card sales of every closed session are added automatically; in the
app the owners withdraw cash from it (to their cash box or for themselves),
pay expenses by card with photos, deposit cash on it and check its balance.

Session Review gains "Cash-outs without receipt" and "Receipts not matched";
each POS can require both to be zero before "Mark as Reviewed".

Developed by Yousif Shakir - Donialink | تطوير يوسف شاكر
    """,
    'author': 'Donialink, Yousif Shakir',
    'maintainer': 'Yousif Shakir',
    'website': 'https://www.donialink.com',
    'license': 'LGPL-3',
    'depends': [
        'expense_cash_control',
        'purchase',
        'telegram_reports',
        'donialink_agent',
        'donialink_app',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/security.xml',
        'security/dl_app_security.xml',
        'data/ir_sequence_data.xml',
        'data/ir_cron_data.xml',
        'wizard/receipt_question_wizard_views.xml',
        'wizard/owner_collection_return_views.xml',
        'wizard/owner_app_access_views.xml',
        'views/telegram_sender_views.xml',
        'views/receipt_views.xml',
        'views/pos_cash_move_views.xml',
        'views/pos_session_views.xml',
        'views/pos_config_views.xml',
        'views/owner_box_views.xml',
        'views/owner_card_views.xml',
        'views/owner_expense_review_views.xml',
        'views/menus.xml',
        'views/dl_app_receipt_views.xml',
        'data/dl_app_data.xml',
        'data/dl_app_kind_data.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'expense_cash_control_telegram/static/src/**/*',
        ],
        # the DoniaLink App (/dl/app): the owner cash box and "Send receipt" screens
        'donialink_app.assets_app': [
            'expense_cash_control_telegram/static/dl_app/cashbox_screen.css',
            'expense_cash_control_telegram/static/dl_app/cashbox_screen.js',
            'expense_cash_control_telegram/static/dl_app/receipt_screen.css',
            'expense_cash_control_telegram/static/dl_app/receipt_screen.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
