/** @odoo-module ignore **/
/* DoniaLink App: "Send receipt": photos of a bill, who paid, the accountant's questions. */
(function () {
    'use strict';
    const app = window.DLApp;
    const { h, t } = app;
    const MAX_PHOTOS = 5;
    const MAX_SIDE = 1600;

    app.text({
        ar: {
            'Send receipt': 'إرسال فاتورة', 'New receipt': 'فاتورة جديدة', 'Add photo': 'إضافة صورة',
            'Take a photo of the bill': 'صوّر الفاتورة', 'Who paid?': 'من دفع؟', 'Cashier': 'الكاشير',
            'Payable (vendor)': 'آجل (على المورد)', 'Amount (optional)': 'المبلغ (اختياري)',
            'Note (optional)': 'ملاحظة (اختياري)', 'What was bought?': 'ماذا تم شراؤه؟', 'Send': 'إرسال',
            'Sending…': 'جارٍ الإرسال…', 'Sent ✓ {0}': 'تم الإرسال ✓ {0}', 'My receipts': 'فواتيري',
            'No receipts yet.': 'لا توجد فواتير بعد.', 'Remove': 'حذف', 'Add a photo of the bill.': 'أضف صورة للفاتورة.',
            'Choose who paid.': 'اختر من دفع.', 'At most {0} photos.': 'بحد أقصى {0} صور.',
            'Question': 'سؤال', 'Questions from the accountant': 'أسئلة المحاسب', 'Your answer': 'جوابك',
            'Answer': 'إجابة', 'Answered': 'تمت الإجابة', 'Waiting for your answer': 'بانتظار جوابك',
            'To Review': 'قيد المراجعة', 'Processed': 'تمت المراجعة', 'Rejected': 'مرفوضة', 'Duplicate': 'مكررة',
            'Answer sent ✓': 'تم إرسال الجواب ✓', 'Photos': 'الصور',
        },
    });

    const STATE = { to_review: 'To Review', processed: 'Processed', rejected: 'Rejected', duplicate: 'Duplicate' };

    function call(action, params) {
        return app.call('/dl/app/receipts/api/' + action, params);
    }

    // a phone photo is 3-8 MB: send it as a JPEG of at most MAX_SIDE pixels
    function shrink(file) {
        return new Promise((resolve, reject) => {
            const url = URL.createObjectURL(file);
            const img = new Image();
            img.onload = () => {
                const scale = Math.min(1, MAX_SIDE / Math.max(img.naturalWidth, img.naturalHeight));
                const canvas = document.createElement('canvas');
                canvas.width = Math.round(img.naturalWidth * scale);
                canvas.height = Math.round(img.naturalHeight * scale);
                canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
                URL.revokeObjectURL(url);
                const dataUrl = canvas.toDataURL('image/jpeg', 0.82);
                resolve({ preview: dataUrl, content_b64: dataUrl.split(',')[1], mimetype: 'image/jpeg',
                    filename: (file.name || 'receipt').replace(/\.[^.]+$/, '') + '.jpg' });
            };
            img.onerror = () => { URL.revokeObjectURL(url); reject(new Error(t('Add a photo of the bill.'))); };
            img.src = url;
        });
    }

    function stateBadge(r) {
        return h('span', { class: 'dl-state dl-state-' + r.state }, t(STATE[r.state] || r.state_label));
    }

    function receiptRow(r) {
        return h('a', { class: 'dl-msg', href: '#receipt/' + r.id }, [
            h('span', { class: 'dl-msg-icon' }, app.icon('receipt')),
            h('span', { class: 'dl-msg-main' }, [
                h('span', { class: 'dl-msg-title' }, [r.reference, ' ', stateBadge(r)]),
                h('span', { class: 'dl-msg-preview' }, [r.amount_text, r.amount_text && r.note ? ' · ' : '', r.note]
                    .filter(Boolean).join('') || r.paid_by_label),
                r.waiting_question ? h('span', { class: 'dl-msg-meta dl-ask' }, t('Waiting for your answer')) : null,
            ]),
            h('span', { class: 'dl-msg-date' }, app.date(r.date)),
        ]);
    }

    function form(onSent) {
        const photos = [];
        let paidBy = '';
        const thumbs = h('div', { class: 'dl-thumbs' });
        const input = h('input', { type: 'file', accept: 'image/*', capture: 'environment', multiple: true, hidden: true });
        const amount = h('input', { class: 'dl-input', type: 'text', inputmode: 'decimal', placeholder: t('Amount (optional)') });
        const note = h('textarea', { class: 'dl-input', rows: '2', placeholder: t('What was bought?') });
        const send = h('button', { class: 'dl-btn', type: 'submit' }, t('Send'));

        function drawThumbs() {
            thumbs.replaceChildren(...photos.map((p, i) => h('span', { class: 'dl-thumb' }, [
                h('img', { src: p.preview, alt: '' }),
                h('button', { type: 'button', class: 'dl-thumb-x', 'aria-label': t('Remove'),
                    onclick: () => { photos.splice(i, 1); drawThumbs(); } }, '×'),
            ])), photos.length < MAX_PHOTOS ? h('button', { type: 'button', class: 'dl-thumb-add',
                onclick: () => input.click() }, [app.icon('camera'), h('span', {}, photos.length ? t('Add photo') : t('Take a photo of the bill'))]) : null);
        }
        input.addEventListener('change', async () => {
            for (const file of Array.from(input.files || [])) {
                if (photos.length >= MAX_PHOTOS) {
                    app.toast(t('At most {0} photos.', MAX_PHOTOS), 'bad');
                    break;
                }
                try {
                    photos.push(await shrink(file));
                } catch (e) {
                    app.toast(e.message, 'bad');
                }
            }
            input.value = '';
            drawThumbs();
        });

        const choices = h('div', { class: 'dl-choices', role: 'radiogroup', 'aria-label': t('Who paid?') },
            [['cashier', 'Cashier'], ['payable', 'Payable (vendor)']].map(([value, label]) => h('button', {
                type: 'button', role: 'radio', 'aria-checked': 'false', 'data-value': value,
                onclick: (ev) => {
                    paidBy = value;
                    choices.querySelectorAll('button').forEach((b) => b.setAttribute('aria-checked', String(b === ev.currentTarget)));
                },
            }, t(label))));

        const formEl = h('form', { class: 'dl-card dl-receipt-form', onsubmit: async (ev) => {
            ev.preventDefault();
            if (!photos.length) {
                return app.toast(t('Add a photo of the bill.'), 'bad');
            }
            if (!paidBy) {
                return app.toast(t('Choose who paid.'), 'bad');
            }
            send.disabled = true;
            send.textContent = t('Sending…');
            try {
                const r = await call('send', {
                    photos: photos.map(({ content_b64, mimetype, filename }) => ({ content_b64, mimetype, filename })),
                    paid_by: paidBy, amount: amount.value.replace(',', '.').trim() || null, note: note.value,
                });
                app.toast(t('Sent ✓ {0}', r.reference), 'ok');
                onSent(r);
            } catch (e) {
                app.toast(e.message, 'bad');
                send.disabled = false;
                send.textContent = t('Send');
            }
        } }, [
            h('h2', {}, t('New receipt')), thumbs, input,
            h('div', { class: 'dl-field' }, [h('span', { class: 'dl-label' }, t('Who paid?')), choices]),
            amount, note, send,
        ]);
        drawThumbs();
        return formEl;
    }

    async function list(el) {
        el.append(app.topbar(t('Send receipt'), true));
        el.append(form(() => app.route()));
        const card = h('section', { class: 'dl-card' }, [h('h2', {}, t('My receipts'))]);
        el.append(card);
        const data = await call('mine', { limit: 20 });
        card.append(data.receipts.length
            ? h('div', { class: 'dl-list' }, data.receipts.map(receiptRow))
            : h('p', { class: 'dl-empty' }, t('No receipts yet.')));
    }

    async function detail(el, id) {
        const r = await call('receipt', { receipt_id: Number(id) });
        el.append(app.topbar(r.reference, true));
        el.append(h('section', { class: 'dl-card' }, [
            h('div', { class: 'dl-row' }, [stateBadge(r), h('span', { class: 'dl-muted' }, app.date(r.date))]),
            h('div', {}, [h('b', {}, r.paid_by_label), r.amount_text ? ' · ' + r.amount_text : '']),
            r.note ? h('p', { class: 'dl-body' }, r.note) : null,
            h('div', { class: 'dl-thumbs' }, r.photos.map((src) => h('a', { class: 'dl-thumb', href: src, target: '_blank' },
                h('img', { src, alt: t('Photos'), loading: 'lazy' })))),
        ]));
        if (!r.questions.length) {
            return;
        }
        el.append(h('section', { class: 'dl-card' }, [h('h2', {}, t('Questions from the accountant'))].concat(
            r.questions.map((q) => {
                const box = h('div', { class: 'dl-question' + (q.state === 'sent' ? ' open' : '') }, [
                    h('div', { class: 'dl-msg-meta' }, [q.by, ' · ', app.date(q.date)]),
                    h('p', { class: 'dl-q-text' }, '❓ ' + q.text),
                ]);
                if (q.state === 'answered') {
                    box.append(h('p', { class: 'dl-q-answer' }, '💬 ' + q.answer));
                } else {
                    const text = h('textarea', { class: 'dl-input', rows: '2', placeholder: t('Your answer') });
                    const btn = h('button', { class: 'dl-btn small', type: 'submit' }, t('Answer'));
                    box.append(h('form', { class: 'dl-answer', onsubmit: async (ev) => {
                        ev.preventDefault();
                        if (!text.value.trim()) {
                            return;
                        }
                        btn.disabled = true;
                        try {
                            await call('answer', { receipt_id: r.id, question_id: q.id, text: text.value });
                            app.toast(t('Answer sent ✓'), 'ok');
                            app.route();
                        } catch (e) {
                            app.toast(e.message, 'bad');
                            btn.disabled = false;
                        }
                    } }, [text, btn]));
                }
                return box;
            }))));
    }

    app.screen('receipt', {
        render(el, params) {
            return params[0] ? detail(el, params[0]) : list(el);
        },
    });
})();
