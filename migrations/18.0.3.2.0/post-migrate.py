# -*- coding: utf-8 -*-
"""Card boxes: the balance now comes from the card's account in the chart of accounts."""


def migrate(cr, version):
    cr.execute("""
        UPDATE ecc_owner_card card SET account_id = journal.default_account_id
          FROM account_journal journal
         WHERE journal.id = card.journal_id AND card.account_id IS NULL
    """)
