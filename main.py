import requests
import base64
import telebot
import os
from telebot.apihelper import ApiTelegramException
from telebot.util import quick_markup
import mysql.connector
from mysql.connector import pooling
import pymorphy2
import json

# telegram bot token
tg_token  = ''
# bot username
tg_name   = 'sohranil_bot'

# yandex cloud token and folder for text recognition api
yc_token  = ''
yc_folder = ''

# database credentials
db_host   = 'localhost'
db_user   = 'root'
db_pwd    = 'root'
db_name   = 'sohranilla'

# list of telegram users that can use bot even if they are not in the chat
whitelist = []
# chat id starting with -
chat_id   = -1001210960846

bot = telebot.TeleBot(tg_token)
me = bot.get_me()

connection_pool = pooling.MySQLConnectionPool(pool_name='pool', pool_reset_session=True, host=db_host, user=db_user, password=db_pwd, database=db_name, pool_size=32)

def encode_file(file):
    with open(file, 'rb') as f:
        file_content = f.read()
    return base64.b64encode(file_content).decode('utf-8')

def recognize(file):
    body = {
        "folderId": yc_folder,
        "analyze_specs": [{
            "content": file,
            "features": [{
                "type": "TEXT_DETECTION",
                "text_detection_config": {
                    "language_codes": ["*"]
                }
            }]
        }]
    }

    headers = {'Content-Type': 'application/json', 'Accept-Charset': 'UTF-8', 'Authorization': 'Api-Key ' + yc_token}
    r = requests.post('https://vision.api.cloud.yandex.net/vision/v1/batchAnalyze', data=str(body), headers=headers)
    results = r.json()['results'][0]['results'][0]['textDetection']['pages'][0]

    if 'blocks' in results:
        blocks = results['blocks']
        answer = ''
        for i in blocks:
            for j in i['lines']:
                for k in j['words']:
                    answer += k['text'] + ' '
                answer += '\n'
        return answer
    
    return 'notext'

def executequery(q, v):
    connection_object = connection_pool.get_connection()
    cursor = connection_object.cursor()

    cursor.execute(q, v)
    connection_object.commit()

    lastrowid = cursor.lastrowid

    cursor.close()
    connection_object.close()

    return lastrowid

def selectquery(q, v):
    connection_object = connection_pool.get_connection()
    cursor = connection_object.cursor()

    cursor.execute(q, v)

    answer = []
    for (id, file_id, date, description, rel) in cursor:
        answer.append((id, file_id, date, description, rel))

    cursor.close()
    connection_object.close()
    return answer

def fix(q, v):
    connection_object = connection_pool.get_connection()
    cursor = connection_object.cursor()

    cursor.execute(q, v)

    exists = False
    for id in cursor:
        exists = True

    cursor.close()
    connection_object.close()
    return exists

def file_id_exists(file_id):
    try:
        return fix('SELECT `id` FROM `files` WHERE `file_id` = %s', [file_id])
    except mysql.connector.errors.OperationalError:
        print('disconnected')
        connection_pool.reconnect(attempts = 100, delay = 10)
        return fix('SELECT `id` FROM `files` WHERE `file_id` = %s', [file_id])
    

def god(q, v):
    connection_object = connection_pool.get_connection()
    cursor = connection_object.cursor()

    cursor.execute(q, v)

    answer = []
    for (id, owner, description, file_id) in cursor:
        answer.append((id, owner, description, file_id))

    cursor.close()
    connection_object.close()
    return answer

def get_owner_data(id):
    try:
        return god('SELECT `id`, `owner`, `description`, `file_id` FROM `files` WHERE `id` = %s', [id])[0]
    except mysql.connector.errors.OperationalError:
        print('disconnected')
        connection_pool.reconnect(attempts = 100, delay = 10)
        return god('SELECT `id`, `owner`, `description`, `file_id` FROM `files` WHERE `id` = %s', [id])[0]
    

def search(q):
    q = q.lower()
    q = q.replace('ё', 'е')
    prepared = q.upper().split(' ')
    
    tags = []

    morph = pymorphy2.MorphAnalyzer(lang='ru')

    for word in prepared:
        pseudo_root = morph.parse(word)[0]

        tags1 = []
        for roots in pseudo_root.lexeme:
            w = roots.word.lower()

            if (len(w) > 3):
                tags1.append(w)
        tags.append('+(' + ' '.join(tags1) + ')')

    return '>("' + q + '") <(' + ' '.join(tags) + ')'

def isInChat(id):
    if id in whitelist:
        return True

    try:
        member = bot.get_chat_member(chat_id, id)
        if(member.status == 'left' or member.status == 'kicked' or member.status == 'restricted'):
            return False

        return member
    except telebot.apihelper.ApiTelegramException:
        return False

@bot.inline_handler(func=lambda query: True)
def query_text(query):
    if(query.query.startswith('!edit')):
        arguments = query.query.split(' ', 2)
        if(len(arguments) == 3):
            id = arguments[1]
            text = arguments[2]
            bot.answer_inline_query(query.id, [telebot.types.InlineQueryResultArticle(id='1', title='Изменить описание мема', input_message_content=telebot.types.InputTextMessageContent('/edit@' + tg_name + ' ' + str(id) + ' ' + text))])
    else:
        offset = 0
        if(len(query.offset) > 0):
            offset = int(query.offset)

        if(len(query.query) > 0):
            s = search(query.query)
            q = 'SELECT `id`, `file_id`, `date`, `description`, MATCH (`description`) AGAINST (%s IN BOOLEAN MODE) AS `rel` FROM `files` WHERE MATCH (`description`) AGAINST (%s IN BOOLEAN MODE) ORDER BY `rel` DESC LIMIT %s, 50'
            v = (s, s, offset)
        else:
            q = 'SELECT `id`, `file_id`, `date`, `description`, 1 AS `rel` FROM `files` ORDER BY `id` DESC LIMIT %s, 50'
            v = [offset]

        try:
            answer = selectquery(q, v)
        except mysql.connector.errors.OperationalError:
            print('disconnected')
            connection_pool.reconnect(attempts = 100, delay = 10)
            answer = selectquery(q, v)

        images = []
        for i in answer:
            images.append(telebot.types.InlineQueryResultCachedPhoto(id=i[0], photo_file_id=i[1]))

        bot.answer_inline_query(query.id, images, cache_time=0, next_offset=offset+50)


@bot.message_handler(commands=['edit'])
def edit(message):
    arguments = message.text.split(' ', 2)
    
    id = int(arguments[1])
    text = arguments[2]
    data = get_owner_data(id)

    markup = quick_markup({
        '✅ Закрыть': {'callback_data': '{"action": "close", "chat": "'+str(message.chat.id)+'"}'}
    }, row_width=1)
    
    if(message.from_user.id == data[1]):
        q = 'UPDATE `files` SET `description` = %s WHERE `id` = %s'
        v = [text, id]
        try:
            executequery(q, v)
        except mysql.connector.errors.OperationalError:
            print('disconnected')
            connection_pool.reconnect(attempts = 100, delay = 10)
            executequery(q, v)

        bot.reply_to(message, 'Готово!', reply_markup=markup)
    else:
        bot.reply_to(message, 'Лее, куда жмёш, эээ, кнопка нэ твоя.', reply_markup=markup)
    

@bot.message_handler(commands=['help', 'start'])
def send_welcome(message):
    if(isInChat(message.from_user.id)):
        bot.reply_to(message, 'Отправь мне картиночку, и я схороню её. Если на ней есть текст, я распознаю его и ты сможешь найти эту пикчу в инлайн-режиме. Также можешь добавить собственное описание в подписи к фотографии.')
    else:
        bot.reply_to(message, 'Этот бот только для элиты, а ты сосо.')

@bot.message_handler(commands=['save'])
def save(message):
    if(isInChat(message.from_user.id)):
        if(message.reply_to_message):
            if(message.reply_to_message.photo):
                add_image(message.reply_to_message, message)
            else:
                bot.reply_to(message, 'Используй эту команду в ответе на пикчу, лалка !)')
        else:
            bot.reply_to(message, 'Используй эту команду в ответе на пикчу, лалка !)')
    else:
        bot.reply_to(message, 'Этот бот только для элиты, а ты сосо.')


@bot.message_handler(func=lambda message: True, content_types=['photo'])
def add_image(message, reply=None):
    if(message.chat.type == 'private' or (reply and message.chat.type != 'private') or (message.caption and '/save' in message.caption)):
        if(isInChat(message.from_user.id)):
            if(message.via_bot and message.via_bot.id == me.id):
                pass
            else:
                file_id = message.photo[-1].file_id

                if(file_id_exists(file_id)):
                    if(reply):
                        bot.reply_to(reply, 'Ещё 10 раз скинь!', parse_mode='MarkDown')
                    else:
                        bot.reply_to(message, 'Ещё 10 раз скинь!', parse_mode='MarkDown')
                else:
                    file_info = bot.get_file(file_id)
                    
                    downloaded_file = bot.download_file(file_info.file_path)

                    b64 = base64.b64encode(downloaded_file).decode('utf-8')
                    answer = recognize(b64)

                    if(message.caption and len(message.caption) > 0):
                        caption = message.caption.replace('/save', '')
                        caption = caption.replace('@' + tg_name, '')
                        if(answer == 'notext'):
                            answer = caption
                        else:
                            answer += ' ' + caption

                    if(reply and len(reply.text) > 0):
                        caption = reply.text.replace('/save', '')
                        caption = caption.replace('@' + tg_name, '')
                        if(answer == 'notext'):
                            answer = caption
                        else:
                            answer += ' ' + caption
                    
                    q = 'INSERT INTO `files` (`owner`, `file_id`, `date`, `description`) VALUES (%s, %s, NOW(), %s)'

                    owner = message.from_user.id
                    if(reply):
                        owner = reply.from_user.id

                    v = (str(owner), file_id, answer)

                    try:
                        lastrowid = executequery(q, v)
                    except mysql.connector.errors.OperationalError:
                        print('disconnected')
                        connection_pool.reconnect(attempts = 100, delay = 10)
                        lastrowid = executequery(q, v)

                    markup = quick_markup({
                        '✏️ Редактировать': {'switch_inline_query_current_chat': '!edit '+str(lastrowid)+' '+str(''.join(answer.split('\n')))},
                        '❌ Удалить': {'callback_data': '{"id": "'+str(lastrowid)+'", "action": "delete", "chat": "'+str(message.chat.id)+'"}'},
                        '✅ Готово': {'callback_data': '{"id": "'+str(lastrowid)+'", "action": "done", "chat": "'+str(message.chat.id)+'"}'}
                    }, row_width=2)

                    msg = 'Схоронил. Можно будет найти по тексту: \n`' + str(''.join(answer.split('\n')) + '`')
                    if(reply):
                        bot.reply_to(reply, msg, parse_mode='MarkDown', reply_markup=markup)
                    else:
                        bot.reply_to(message, msg, parse_mode='MarkDown', reply_markup=markup)
        else:
            bot.reply_to(message, 'Этот бот только для элиты, а ты сосо.')

@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call):
    calldata = json.loads(call.data)

    if('id' in calldata):
        data = get_owner_data(calldata['id'])

        if(call.from_user.id == data[1]):
            if(calldata['action'] == 'done'):
                bot.answer_callback_query(call.id, text='ОК!')
                bot.delete_message(calldata['chat'], call.message.id)

                # uncomment if you want to store posts in a telegram channel (bot needs to be an admin of the channel)
                # bot.send_photo(chat_id='@sohranilla', caption=(telebot.formatting.escape_markdown(data[2]) + "\n\nID: " + str(data[0]) + "\n[via](tg://user?id=" + str(data[1]) + ")"), photo=data[3], parse_mode='MarkDown')

            elif(calldata['action'] == 'delete'):
                q = 'DELETE FROM `files` WHERE `id` = %s'
                v = [calldata['id']]
                try:
                    executequery(q, v)
                except mysql.connector.errors.OperationalError:
                    print('disconnected')
                    connection_pool.reconnect(attempts = 100, delay = 10)
                    executequery(q, v)

                bot.answer_callback_query(call.id, text='Ну всё, удоляю!')
                bot.delete_message(calldata['chat'], call.message.id)
            elif(calldata['action'] == 'edit'):
                bot.answer_callback_query(call.id, text='Введи новое описание')
                bot.delete_message(calldata['chat'], call.message.id)
        else:
            bot.answer_callback_query(call.id, text='Лее, куда жмёш, эээ, кнопка нэ твоя.')
    elif('action' in calldata and calldata['action'] == 'close'):
            bot.answer_callback_query(call.id, text='ОК!')
            bot.delete_message(calldata['chat'], call.message.id)
    else:
        bot.answer_callback_query(call.id, text='Я себя зафигарил(')
    
    
bot.infinity_polling()