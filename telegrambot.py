from telegram.ext import Updater, Filters, CommandHandler, MessageHandler, CallbackQueryHandler
from telegram.inlinekeyboardmarkup import InlineKeyboardMarkup
from telegram.inlinekeyboardbutton import InlineKeyboardButton
from telegram.parsemode import ParseMode
from database import Transaction
import json
import traceback


PRIVATE_CHAT = 'private'
ACTION_NEWBILL_SET_NAME = 0
ACTION_ADD_NEW_ITEM = 1
ACTION_EDIT_ITEM = 2
ACTION_DELETE_ITEM = 3
ACTION_ADD_TAX = 4
ACTION_EDIT_TAX = 5
ACTION_DELETE_TAX = 6
ACTION_CREATE_BILL_DONE = 7
REQUEST_BILL_NAME = "Send me a name for the new bill you want to create."
ERROR_INVALID_BILL_NAME = "Sorry, the bill name provided is invalid. Name of the bill can only be 250 characters long."
ERROR_SOMETHING_WENT_WRONG = "Sorry, an error has occurred. Please try again in a few moments."
JSON_ACTION_FIELD = 'a'
JSON_BILL_FIELD = 'b'
EMOJI_MONEY_BAG = '\u1F4B0'
EMOJI_TAX = '\u1F4B8'


class TelegramBot:
    def __init__(self, token, db):
        self.db = db
        self.updater = Updater(token=token)
        self.init_handlers(self.updater.dispatcher)

    def start_bot(self):
        self.updater.start_polling()

    def init_handlers(self, dispatcher):
        # Command handlers
        start_handler = CommandHandler('start', self.start)
        dispatcher.add_handler(start_handler)
        newbill_handler = CommandHandler('newbill', self.new_bill)
        dispatcher.add_handler(newbill_handler)

        # Handle callback queries
        callback_handler = CallbackQueryHandler(self.handle_all_callback)
        dispatcher.add_handler(callback_handler)

        # Handle all replies
        message_handler = MessageHandler(Filters.all, self.handle_all_msg)
        dispatcher.add_handler(message_handler)

    def start(self, bot, update):
        # TODO: make command list screen
        bot.sendMessage(chat_id=update.message.chat_id, text="Start screen")

    def new_bill(self, bot, update):
        # only allow private message
        try:
            conn = self.db.get_connection()
            with Transaction(conn) as trans:
                self.set_session(
                    update.message,
                    ACTION_NEWBILL_SET_NAME,
                    trans
                )
            bot.sendMessage(
                chat_id=update.message.chat_id,
                text=REQUEST_BILL_NAME
            )
        except Exception as e:
            traceback.print_trace()

    def handle_all_msg(self, bot, update):
        try:
            if update.message.chat.type != PRIVATE_CHAT:
                return

            conn = self.db.get_connection()
            msg = update.message
            with Transaction(conn) as trans:
                try:
                    pending_action = trans.get_pending_action(
                        msg.from_user.id,
                        msg.chat_id
                    )
                    if pending_action == ACTION_NEWBILL_SET_NAME:
                        return self.add_bill_name(msg, bot, trans)
                except Exception as e:
                    traceback.print_trace()
        except:
            traceback.print_trace()

    def handle_all_callback(self, bot, update):
        cb = update.callback_query
        data = cb.data

        if data is None:
            return cb.answer()

        payload = json.loads(data)
        action = payload.get(JSON_ACTION_FIELD)

        if action is None:
            return cb.answer('nothing')
        if action == ACTION_ADD_NEW_ITEM:
            return cb.answer('Add')
        if action == ACTION_EDIT_ITEM:
            return cb.answer('Edit')
        if action == ACTION_CREATE_BILL_DONE:
            return cb.answer('Done')

    def set_session(self, message, action_type, trans):
        user = message.from_user
        trans.add_user(
            user.id,
            user.first_name,
            user.last_name,
            user.username
        )
        trans.add_session(message.chat_id, user.id, action_type)

    def add_bill_name(self, msg, bot, trans):
        try:
            if not Filters.text.filter(msg):
                return bot.sendMessage(
                    chat_id=msg.chat_id,
                    text=ERROR_INVALID_BILL_NAME
                )

            text = msg.text
            if (text is None or len(text) < 1 or len(text) > 250):
                return bot.sendMessage(
                    chat_id=msg.chat_id,
                    text=ERROR_INVALID_BILL_NAME
                )

            bill_id = trans.create_new_bill(text, msg.from_user.id)
            trans.reset_action(msg.from_user.id, msg.chat_id)
            return bot.sendMessage(
                chat_id=msg.chat_id,
                text=self.get_bill_text(bill_id, msg.from_user.id, trans),
                parse_mode=ParseMode.HTML,
                reply_markup=self.get_new_bill_keyboard(bill_id)
            )
        except BillError as e:
            return bot.sendMessage(
                chat_id=msg.chat_id,
                text=str(e)
            )
        except Exception as e:
            print(e)
            traceback.print_trace()
            return bot.sendMessage(
                chat_id=msg.chat_id,
                text=ERROR_SOMETHING_WENT_WRONG
            )

    def get_bill_text(self, bill_id, user_id, trans):
        bill = trans.get_bill_details(bill_id, user_id)
        if bill.get('title') is None or len(bill.get('title')) == 0:
            raise BillError('Bill does not exist')

        title_text = '<b>{}</b>'.format(self.escape_html(bill['title']))

        bill_items = bill.get('items')
        items_text = []
        total = 0
        if bill_items is None or len(bill_items) < 1:
            items_text.append('<i>Currently no items</i>')
        else:
            for i, item in enumerate(bill_items):
                title, price = item
                total += price

                items_text.append(str(i) + '. ' + title + '\n' +
                                  EMOJI_MONEY_BAG + str(price))

        bill_taxes = bill.get('taxes')
        taxes_text = []
        if bill_taxes is not None:
            for title, tax in bill_taxes:
                total += (tax * total / 100)
                taxes_text.append(EMOJI_TAX + ' ' + title + ': ' + tax + '%')

        text = title_text + '\n\n' + '\n'.join(items_text)
        if len(taxes_text) > 0:
            text += '\n\n' + '\n'.join(taxes_text)

        text += '\n\n' + 'Total: ' + str(total)
        return text

    def get_new_bill_keyboard(self, bill_id):
        add_item_btn = InlineKeyboardButton(
            text="Add item(s)",
            callback_data=self.get_action_callback_data(
                ACTION_ADD_NEW_ITEM,
                bill_id
            )
        )
        edit_item_btn = InlineKeyboardButton(
            text="Edit item",
            callback_data=self.get_action_callback_data(
                ACTION_EDIT_ITEM,
                bill_id
            )
        )
        del_item_btn = InlineKeyboardButton(
            text="Delete item",
            callback_data=self.get_action_callback_data(
                ACTION_DELETE_ITEM,
                bill_id
            )
        )
        add_tax_btn = InlineKeyboardButton(
            text="Add item(s)",
            callback_data=self.get_action_callback_data(
                ACTION_ADD_TAX,
                bill_id
            )
        )
        edit_tax_btn = InlineKeyboardButton(
            text="Edit item",
            callback_data=self.get_action_callback_data(
                ACTION_EDIT_TAX,
                bill_id
            )
        )
        del_tax_btn = InlineKeyboardButton(
            text="Delete item",
            callback_data=self.get_action_callback_data(
                ACTION_DELETE_TAX,
                bill_id
            )
        )
        done_btn = InlineKeyboardButton(
            text="Done",
            callback_data=self.get_action_callback_data(
                ACTION_CREATE_BILL_DONE,
                bill_id
            )
        )
        return InlineKeyboardMarkup(
            [[add_item_btn],
             [edit_item_btn],
             [del_item_btn],
             [add_tax_btn],
             [edit_tax_btn],
             [del_tax_btn],
             [done_btn]]
        )

    def get_action_callback_data(self, action, bill_id):
        data = {
            JSON_ACTION_FIELD: action,
            JSON_BILL_FIELD: bill_id
        }
        return json.dumps(data)

    @staticmethod
    def escape_html(s):
        arr = s.split('&')
        escaped = []

        for sgmt in arr:
            a = sgmt.replace('<', '&lt;')
            a = a.replace('>', '&gt;')
            escaped.append(a)

        return '&amp;'.join(escaped)


class BillError(Exception):
    pass
