import telebot
from openai import OpenAI
import logging
import time
import io
import os
import psutil
from image_handling import create_image_content

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

OPENAI_API_KEY_TELEGRAM = os.getenv('OPENAI_API_KEY_TELEGRAM')
client = OpenAI(
    # This is the default and can be omitted
    api_key=OPENAI_API_KEY_TELEGRAM,
)

wellcome_phrase = "Для начала работы выберите режим."
translation_prompt = 'You are the best language translator in the world. User will provide you with text to translate.'
chatgpt_storage_time = 3600 * 24 # 24 hours

users_cache = {}
mode_switcher_ext = [
    { 'command' : '/rusrb', 'text' : 'Режим перевода с русского на сербский', 'mode': 'translator', 'src_lang' : 'russian', 'dst_lang' : 'serbian' },
    { 'command' : '/srbru', 'text' : 'Режим перевода с сербского на русский', 'mode': 'translator', 'src_lang' : 'serbian', 'dst_lang' : 'russian' },
    { 'command' : '/ensrb', 'text' : 'Translation mode from English to Serbian', 'mode': 'translator', 'src_lang' : 'english', 'dst_lang' : 'serbian' },
    { 'command' : '/srben', 'text' : 'Translation mode from Serbian to English', 'mode': 'translator', 'src_lang' : 'serbian', 'dst_lang' : 'english' },
    { 'command' : '/chatgpt', 'text' : 'Чат с ботом напрямую (ChatGPT 4o mini)', 'mode': 'chatgpt' },
    { 'command' : '/image', 'text' : 'Сгенерировать изображение (Dall-E 2)', 'mode': 'dalle' }
]


logging.basicConfig(handlers=[
                        logging.FileHandler(filename="translator_bot.log", 
                        encoding='utf-8', mode='a+')
                    ],
                    format="%(asctime)s %(name)s:%(levelname)s:%(message)s", 
                    datefmt="%F %A %T", 
                    level=logging.INFO)

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, wellcome_phrase)

@bot.message_handler(content_types=['text'])
def handle_text(message):
    handle_messages(message, "text")


@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    handle_messages(message, "photo")

@bot.message_handler(content_types=['document'])
def handle_other(message):
    handle_messages(message, "document")

@bot.message_handler(content_types=['voice'])
def handle_voice(message):
    handle_messages(message, "voice")

@bot.message_handler(content_types=['audio'])
def handle_audio(message):
    handle_messages(message, "audio")

def handle_messages(message, type):

    user_id = message.from_user.id
    user_text = message.text
    current_cache = {}
    if user_id in users_cache:
        current_cache = users_cache[user_id]

    is_first_message = not bool(current_cache)
    is_command = False
    # firstly check if user input is a command
    for item in mode_switcher_ext:
        if user_text == item['command']:
            is_command = True
            current_cache["command"] = item['command']
            current_cache["messages"] = []  # clear messages cache
            # save current time as last message time
            current_cache["last_message_time"] = int(time.time())
            current_cache["mode_metadata"] = item
            bot.send_message(user_id, item['text'])
            log_add(f"User command: {item['command']}, text: {item['text']}")
            break
    if is_command:
        users_cache[user_id] = current_cache
        return
    
    # wellcome phrase for any first input except commands
    if not is_command and is_first_message:
        bot.send_message(user_id, wellcome_phrase)
        log_add('User joined, user_id: '+str(user_id))
        return 
    
    mode_metadata = current_cache['mode_metadata']

    # image generation processing
    if mode_metadata['mode'] == 'dalle':
        log_add(f"Generate image for user {user_id}, input: {user_text}")
        # call dall e service
        images_response = client.images.generate(
            model="dall-e-2",
            prompt=user_text,
            n=1,
            size="1024x1024"
        )
        created_dt_images = images_response.created
        generated_images = images_response.data
        if len(generated_images) > 0:
            image = generated_images[0]
            image_url = image.url
            bot.send_photo(user_id, image_url)
            log_add(f"Image sent to user {user_id}, image url: {image_url}")
        return

    # audio processing
    if type == "voice" or type == "audio":
        log_add(f"User {user_id} voice message")
        if type == "voice":
            voice_bytes = extract_voice(message)
        elif type == "audio":
            voice_bytes = extract_audio(message)
        #voice_bytes = extract_voice(message)
        audio_file = io.BytesIO(voice_bytes)
        audio_file.name = "voice_message.ogg"
        transcription = client.audio.transcriptions.create(
            file=audio_file,
            model="whisper-1",
            response_format="text"
        )
        user_text = transcription 
        log_add(f"User {user_id} recognized text: {user_text}")
        bot.send_message(message.from_user.id, user_text + "\n" + "*** Recognized text ***")
        type = "text"

    # messages processing
    messages = []
    if mode_metadata['mode'] == 'translator':
        log_add(f"Translating user {user_id} text: {user_text}, command: {mode_metadata['command']}")
        process_translation(messages, user_text, mode_metadata['src_lang'], mode_metadata['dst_lang'])
    elif mode_metadata['mode'] == 'chatgpt':
        # check last message time and delete old history if needed
        last_message_time = current_cache.get("last_message_time", 0)
        if last_message_time > 0 and int(time.time()) > last_message_time + chatgpt_storage_time:
            current_cache["messages"] = []
        messages = current_cache["messages"]    # load history
        log_add(f"ChatGPT chat with user {user_id}, history have {len(messages)} messages: ")
        process_chatgpt(messages, user_text, user_id, type, message)
    else:
        log_add(f"Unknown mode: {mode_metadata['mode']}")
        return  # unknown mode
                   
    chat_completion = client.chat.completions.create(
        messages=messages,
        model="gpt-4o-mini",
    )
    text_answer = chat_completion.choices[0].message.content
    text_answer_with_info = text_answer
    if len(messages) > 1:
        text_answer_with_info = text_answer_with_info + '\n\n' + "*** Used history with last " + str(len(messages)) + " messages ***"
    log_add('ChatGPT answer for user '+str(user_id)+': '+text_answer_with_info)
    bot.send_message(message.from_user.id, text_answer_with_info)
    if mode_metadata['mode'] == 'chatgpt':
        messages.append({
            "role": "assistant",
            "content": text_answer,
        })
        current_cache["messages"] = messages

    users_cache[user_id] = current_cache

def process_translation(messages, input_text, src_language, dest_language):
    messages.append({
        "role": "system",
        "content": translation_prompt,                  
    })  
    messages.append({
        "role": "user",
        "content": 'Translate text in angle brackets from ' + src_language + ' to '+ dest_language + ': <' + input_text + '>',
    })

def process_chatgpt(messages, user_text, user_id, type, message):
    log_add("Process type: "+type)
    if type=="text":
        messages.append({
            "role": "user",
            "content": user_text,                  
        })
        log_add(f"User {user_id} text: {user_text}")
    elif type=="photo":
        photo_bytes = extract_photo(message)
        content_image, info_message = create_image_content(photo_bytes)
        log_add(f"User {user_id} {info_message}")
        messages.append({
            "role": "user",
            "content": [
                content_image
            ],
        })
    elif type=="document":
        doc_bytes = extract_document(message)
        content_image, info_message = create_image_content(doc_bytes)
        log_add(f"User {user_id} {info_message}")
        messages.append({
            "role": "user",
            "content": [
                content_image
            ],
        })


def extract_photo(message):
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    return downloaded_file

def extract_document(message):
    file_info = bot.get_file(message.document.file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    return downloaded_file

def extract_voice(message):
    file_info = bot.get_file(message.voice.file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    return downloaded_file

def extract_audio(message):
    file_info = bot.get_file(message.audio.file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    return downloaded_file

def log_add(text):
    print(text)
    logging.info(text)
        
#bot.polling(none_stop=True, interval=0)
bot.infinity_polling(timeout=10, long_polling_timeout = 5)

''' bot commands:
rusrb - Режим перевода с русского на сербский
srbru - Режим перевода с сербского на русский
ensrb - Translation mode from English to Serbian
srben - Translation mode from Serbian to English
chatgpt - Чат с ботом напрямую (ChatGPT 4o mini)
image - Сгенерировать изображение (Dall-E 2)
'''