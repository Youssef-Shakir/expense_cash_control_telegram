# -*- coding: utf-8 -*-
{
    'name': 'Expenses & Cash Control - Telegram Receipts',
    'version': '18.0.4.1.0',
    'category': 'Accounting/Expenses',
    'summary': 'Staff send bill photos to the DoniaLink Telegram bot; the accountant reviews them in Odoo',
    'description': """
Telegram Receipt Capture | استلام الفواتير عبر تيليجرام
=======================================================================

Client staff post bill photos in their Telegram group. The DoniaLink bot
(run by the DoniaLink Platform) asks who paid it and for a note, then sends
the photo to this database. The accountant reviews every receipt in one inbox:

* Payable  -> create a purchase order (RFQ) prefilled with the vendor and the photo;
  a "To Pay Later" expense stays available for service costs
* Cashier  -> match it to the POS cash-out it proves (never a second expense)
* Ask the sender a question: the bot posts it under the photo, the answer
  comes back in the receipt chatter
* Reject / mark duplicate (photos already received are flagged)

Owner cash box (phase 2): each owner / partner collects the cash of closed
POS sessions, records expenses, "took for me" and deposits from a private chat
with the bot; his balance is computed by Odoo, weekly or monthly statements
to confirm, differences explained by the accountant.

Owner App (installable web app, /ecc/owner/app): the same owner cash box in a
phone app - balance, collect sessions, expenses with photos, took for me,
deposits, count my cash, history and statements. Works alongside the bot;
the accountant gives access with "Owner App Access" (a free portal login).

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
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/security.xml',
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
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'expense_cash_control_telegram/static/src/**/*',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}
