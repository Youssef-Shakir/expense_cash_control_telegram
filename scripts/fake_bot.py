#!/usr/bin/env python3
"""Fake DoniaLink bot: calls the receipt tools exactly like the DoniaLink Platform will, so the Odoo
side can be tested before the platform's Telegram flow exists. Standard library only.

    export ODOO_URL=http://localhost:8069 ODOO_DB=steve AGENT_KEY=<agent API key>

    # a staff member posts a photo, answers "Cashier" and types a note
    python3 fake_bot.py photo bill.jpg --paid cashier --note "gas cylinder"
    # an album of two photos, nobody answers (stays "Not specified")
    python3 fake_bot.py photo p1.jpg p2.jpg
    # the same picture forwarded again -> flagged as duplicate
    python3 fake_bot.py photo bill.jpg --file-id same-telegram-file
    # someone replies under the photo / under an accountant question (use the message id printed)
    python3 fake_bot.py reply 1730000001 "it was 25,000"

    # owner cash box (private chat): link once with the code shown on the box in Odoo, then use box_id
    python3 fake_bot.py --user 5550001 owner link K7Q2M9XW3P
    python3 fake_bot.py --user 5550001 owner card 1
    python3 fake_bot.py --user 5550001 owner sessions 1
    python3 fake_bot.py --user 5550001 owner collect 1 --session 64 [--amount 500000]
    python3 fake_bot.py --user 5550001 owner categories 1
    python3 fake_bot.py --user 5550001 owner expense 1 --amount 75000 --category 3 --note "generator" --photo bill.jpg
    python3 fake_bot.py --user 5550001 owner took 1 --amount 100000
    python3 fake_bot.py --user 5550001 owner deposit 1 --amount 200000 --target bank
    python3 fake_bot.py --user 5550001 owner moves 1
    python3 fake_bot.py --user 5550001 owner count 1 --amount 3400000
    python3 fake_bot.py --user 5550001 owner statement 1 --statement 4 --wrong --note "I had more"
"""
import argparse
import base64
import datetime
import http.cookiejar
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def opener_for(url, db):
    jar = http.cookiejar.CookieJar()
    if db:   # several databases on one server: get a session cookie on that database first
        first = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), _NoRedirect())
        try:
            first.open(f'{url}/web/login?db={db}').read()
        except urllib.error.HTTPError:
            pass   # the redirect after selecting the database: the cookie is already set
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def call(opener, url, key, tool, params):
    request = urllib.request.Request(
        f'{url}/donialink/agent/v1/tools/{tool}',
        data=json.dumps({'params': params, 'actor': {'id': 'fake-bot', 'name': 'Fake Telegram bot'}}).encode(),
        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'})
    try:
        answer = json.loads(opener.open(request).read())
    except urllib.error.HTTPError as e:
        answer = json.loads(e.read() or b'{}')
    if not answer.get('ok'):
        error = answer.get('error') or {}
        print(f'  ✖ {tool}: {error.get("code")} — {error.get("message")}')
        return None
    return answer['result']


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--url', default=os.environ.get('ODOO_URL', 'http://localhost:8069'))
    parser.add_argument('--db', default=os.environ.get('ODOO_DB'))
    parser.add_argument('--key', default=os.environ.get('AGENT_KEY'))
    parser.add_argument('--company', type=int, default=int(os.environ.get('ODOO_COMPANY', '1')))
    parser.add_argument('--chat', default='-100999', help='Telegram chat id of the fake group')
    parser.add_argument('--user', default='111', help='Telegram user id of the sender')
    parser.add_argument('--name', default='Ali')
    sub = parser.add_subparsers(dest='command', required=True)
    photo = sub.add_parser('photo', help='post one photo or an album')
    photo.add_argument('images', nargs='+')
    photo.add_argument('--paid', choices=['cashier', 'payable'])
    photo.add_argument('--note')
    photo.add_argument('--caption')
    photo.add_argument('--file-id', help='Telegram file_unique_id (same value = same file forwarded)')
    reply = sub.add_parser('reply', help='reply under a photo or an accountant question')
    reply.add_argument('reply_to', type=int)
    reply.add_argument('text')
    owner = sub.add_parser('owner', help='owner cash box (private chat)')
    owner.add_argument('action', choices=['link', 'card', 'sessions', 'collect', 'categories', 'expense', 'took',
                                          'deposit', 'moves', 'count', 'statement'])
    owner.add_argument('box_or_code', help='box id (link: the link code)')
    owner.add_argument('--session', type=int)
    owner.add_argument('--amount', type=float)
    owner.add_argument('--category', type=int)
    owner.add_argument('--note')
    owner.add_argument('--photo')
    owner.add_argument('--target', choices=['bank', 'till'], default='bank')
    owner.add_argument('--statement', type=int)
    owner.add_argument('--wrong', action='store_true', help='statement: Not correct')
    args = parser.parse_args()
    if not args.key:
        sys.exit('Set AGENT_KEY (or --key).')

    opener = opener_for(args.url, args.db)
    sender = {'telegram_user_id': args.user, 'name': args.name}
    base = {'company_id': args.company, 'chat_id': args.chat}

    if args.command == 'owner':
        return run_owner(opener, args, sender)

    if args.command == 'reply':
        result = call(opener, args.url, args.key, 'receipt_reply', dict(
            base, reply_to_message_id=args.reply_to, message_id=int(time.time() * 1000) % 2**31,
            sender=sender, text=args.text))
        if result:
            print(f'  ✓ reply saved on {result["reference"]}')
        return

    album = f'album-{time.time_ns()}' if len(args.images) > 1 else None
    receipt = None
    for index, path in enumerate(args.images):
        with open(path, 'rb') as f:
            content = f.read()
        message_id = int(time.time() * 1000) % 2**31 + index
        result = call(opener, args.url, args.key, 'receipt_create', dict(
            base, chat_title='Fake staff group', message_id=message_id, media_group_id=album, sender=sender,
            sent_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            caption=args.caption if index == 0 else None,
            photo={'content_b64': base64.b64encode(content).decode(), 'filename': os.path.basename(path),
                   'mimetype': mimetypes.guess_type(path)[0] or 'image/jpeg',
                   'file_unique_id': (args.file_id if index == 0 else None) if args.file_id else None}))
        if not result:
            return
        receipt = result
        print(f'  📷 message {message_id} → {result["reference"]} (new receipt: {result["is_new_receipt"]})')
    if receipt['duplicate_of']:
        print(f'  bot: looks like {receipt["duplicate_of"]["reference"]} again')
    print('  bot: Who paid this bill?  [Cashier] [Payable]')
    if args.paid or args.note:
        receipt = call(opener, args.url, args.key, 'receipt_update', {
            'receipt_id': receipt['receipt_id'], 'telegram_user_id': args.user,
            'paid_by': args.paid, 'note': args.note}) or receipt
    else:
        print('  (no answer: stays "Not specified")')
    print(f'  bot: {receipt["summary_text"]}')


def run_owner(opener, args, sender):
    if args.action == 'link':
        result = call(opener, args.url, args.key, 'owner_link', {
            'code': args.box_or_code, 'telegram_user_id': args.user, 'name': args.name})
        if result:
            print(f'  ✓ linked to box {result["box_id"]} ({result["owner"]}, {result["company"]})')
            print(f'  bot: {result["text"]}')
        return
    base = {'box_id': int(args.box_or_code), 'telegram_user_id': args.user}
    tool, params = {
        'card': ('owner_card', {}),
        'sessions': ('owner_sessions', {}),
        'collect': ('owner_collect', {'session_id': args.session, 'amount': args.amount}),
        'categories': ('owner_categories', {}),
        'expense': ('owner_expense', {'amount': args.amount, 'category_id': args.category, 'note': args.note}),
        'took': ('owner_took', {'amount': args.amount, 'note': args.note}),
        'deposit': ('owner_deposit', {'amount': args.amount, 'target': args.target, 'note': args.note}),
        'moves': ('owner_moves', {}),
        'count': ('owner_count', {'counted': args.amount}),
        'statement': ('owner_statement_answer', {'statement_id': args.statement, 'correct': not args.wrong,
                                                 'note': args.note}),
    }[args.action]
    if args.action == 'expense' and args.photo:
        with open(args.photo, 'rb') as f:
            params['photos'] = [{'content_b64': base64.b64encode(f.read()).decode(),
                                 'filename': os.path.basename(args.photo)}]
    params = {k: v for k, v in params.items() if v is not None}
    result = call(opener, args.url, args.key, tool, dict(base, **params))
    if not result:
        return
    if args.action == 'sessions':
        for row in result['sessions'] or [{'name': 'nothing to collect', 'amount_text': '', 'session_id': '-'}]:
            print(f'  [{row["session_id"]}] {row["name"]} {row.get("closed_at") or ""} {row["amount_text"]}')
    elif args.action == 'categories':
        for row in result['categories']:
            print(f'  [{row["id"]}] {row["name"]}')
    else:
        print(f'  bot: {result["text"]}')


if __name__ == '__main__':
    main()
