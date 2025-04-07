import logging
import random
import os
import asyncio
import json
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message, FSInputFile, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.filters.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from gtts import gTTS
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

# Initialize bot and dispatcher with memory storage for FSM
storage = MemoryStorage()
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=storage)

# Function to load words from file
def load_words_from_file(filename="words.txt"):
    words = {}
    try:
        # Попытка загрузить файл в формате JSON
        try:
            with open(filename, 'r', encoding='utf-8') as file:
                words = json.load(file)
        except json.JSONDecodeError:
            # Если не JSON, пробуем формат "слово:перевод" построчно
            words = {}
            with open(filename, 'r', encoding='utf-8') as file:
                for line in file:
                    line = line.strip()
                    if line and ':' in line:
                        word, translation = line.split(':', 1)
                        words[word.strip()] = translation.strip()

        logging.info(f"Загружено {len(words)} слов из файла {filename}")
        return words
    except FileNotFoundError:
        logging.warning(f"Файл {filename} не найден. Используем словарь по умолчанию.")
        # Default dictionary in case file is not found
        return {
            "cat": "кот",
            "dog": "собака",
            "apple": "яблоко",
            "book": "книга",
            "sun": "солнце"
        }

# Load words from file
words = load_words_from_file()

# Defining states for FSM
class QuizStates(StatesGroup):
    ENGLISH_TO_RUSSIAN = State()
    RUSSIAN_TO_ENGLISH = State()

# Function to generate audio
def generate_audio(word):
    tts = gTTS(text=word, lang="en")
    filename = f"{word}.mp3"
    tts.save(filename)
    return filename

# Function to create a keyboard with common commands
def get_common_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="/word")],
            [KeyboardButton(text="/test")],
            [KeyboardButton(text="/clear")],
            [KeyboardButton(text="/reload")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )

# Command to reload words from file
@dp.message(Command("reload"))
async def reload_words(message: Message):
    global words
    words = load_words_from_file()
    await message.answer(f"Словарь обновлен. Загружено {len(words)} слов.", reply_markup=get_common_keyboard())

# Command to clear dialog state
@dp.message(Command("clear"))
async def clear_dialog(message: Message, state: FSMContext):
    # Полностью очищаем состояние пользователя
    await state.clear()
    # Сообщаем пользователю, что диалог очищен
    await message.answer("Диалог очищен. Все прогресс изучения сброшен.", reply_markup=get_common_keyboard())
    await message.answer("Чтобы начать заново, используйте команду /word для изучения новых слов.")

@dp.message(Command("start"))
async def send_welcome(message: Message):
    keyboard = get_common_keyboard()
    await message.answer("Привет! Я помогу тебе учить английские слова. Вот доступные команды:", reply_markup=keyboard)
    await message.answer("/word - получить новое слово для изучения\n/test - начать тестирование\n/clear - очистить прогресс\n/reload - обновить словарь слов")

@dp.message(Command("word"))
async def send_word(message: Message, state: FSMContext):
    # Get user data
    data = await state.get_data()
    current_words = data.get("current_words", [])

    # Check if we already have 5 words
    if len(current_words) >= 5:
        await message.answer("У вас уже есть 5 слов для изучения. Пройдите тест с /test", reply_markup=get_common_keyboard())
        return

    # Choose a new word that isn't already in the current set
    available_words = [(word, translation) for word, translation in words.items()
                        if word.lower() not in [w.lower() for w, _ in current_words]]

    if not available_words:
        await message.answer("Поздравляю! Вы выучили все доступные слова!", reply_markup=get_common_keyboard())
        return

    word, translation = random.choice(available_words)
    current_words.append((word, translation))

    # Save updated words to state
    await state.update_data(current_words=current_words)

    # Send word with translation
    await message.answer(f"{word} - {translation}")

    # Generate and send audio
    audio_file = generate_audio(word)
    voice = FSInputFile(audio_file)
    await bot.send_voice(message.chat.id, voice)
    os.remove(audio_file)

    # Inform user about progress
    if len(current_words) < 5:
        await message.answer(f"Изучено {len(current_words)} из 5 слов. Нажмите /word для следующего слова.", reply_markup=get_common_keyboard())
    else:
        await message.answer("Вы изучили 5 слов! Теперь можете проверить свои знания с помощью /test", reply_markup=get_common_keyboard())

@dp.message(Command("test"))
async def start_test(message: Message, state: FSMContext):
    # Get user data
    data = await state.get_data()
    current_words = data.get("current_words", [])

    if len(current_words) < 5:
        await message.answer(f"Сначала изучите 5 слов! Сейчас у вас {len(current_words)}. Используйте /word для изучения.", reply_markup=get_common_keyboard())
        return

    # Shuffle words for the quiz
    random.shuffle(current_words)

    # Save quiz data
    await state.update_data(
        quiz_words=current_words,
        current_question=0,
        correct_answers=0,
        quiz_stage="eng_to_rus"
    )

    # Start English to Russian quiz
    await state.set_state(QuizStates.ENGLISH_TO_RUSSIAN)
    await send_next_question(message, state)

async def send_next_question(message: Message, state: FSMContext):
    # Get quiz data
    data = await state.get_data()
    quiz_words = data.get("quiz_words", [])
    current_q = data.get("current_question", 0)
    quiz_stage = data.get("quiz_stage", "eng_to_rus")

    # Check if we completed the current quiz stage
    if current_q >= len(quiz_words):
        if quiz_stage == "eng_to_rus":
            # Switch to Russian to English quiz
            await state.update_data(current_question=0, quiz_stage="rus_to_eng")
            await state.set_state(QuizStates.RUSSIAN_TO_ENGLISH)
            await message.answer("Теперь переведите с русского на английский!")
            await send_next_question(message, state)
        else:
            # Quiz is complete
            correct_answers = data.get("correct_answers", 0)
            total_questions = len(quiz_words) * 2  # Both directions

            if correct_answers == total_questions:
                await message.answer(f"🎉 Поздравляю! Вы правильно ответили на все {total_questions} вопросов!", reply_markup=get_common_keyboard())
            else:
                await message.answer(f"Тест завершен! Ваш результат: {correct_answers} из {total_questions} правильных ответов.", reply_markup=get_common_keyboard())

            # Clear current words to start a new set
            await state.update_data(current_words=[])
            await state.clear()
            await message.answer("Используйте /word для изучения новых слов.")
        return

    # Get current word pair
    word, translation = quiz_words[current_q]

    # Prepare answer options
    if quiz_stage == "eng_to_rus":
        question = word
        correct_answer = translation
        # Get 4 random Russian translations for options
        options = [translation]
        other_translations = [t for _, t in words.items() if t.lower() != translation.lower()]
        options.extend(random.sample(other_translations, min(3, len(other_translations))))
    else:  # Russian to English
        question = translation
        correct_answer = word
        # Get 4 random English words for options
        options = [word]
        other_words = [w for w in words.keys() if w.lower() != word.lower()]
        options.extend(random.sample(other_words, min(3, len(other_words))))

    # Shuffle options
    random.shuffle(options)

    # Save correct answer for checking (сохраняем и оригинал и нижний регистр)
    await state.update_data(
        correct_answer=correct_answer,
        correct_answer_lower=correct_answer.lower()
    )

    # Create keyboard with answer options and common commands
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=option) for option in options],
            [KeyboardButton(text="/word")],
            [KeyboardButton(text="/test")],
            [KeyboardButton(text="/clear")],
            [KeyboardButton(text="/reload")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

    # Ask question
    if quiz_stage == "eng_to_rus":
        await message.answer(f"Переведите на русский: **{question}**", parse_mode="Markdown", reply_markup=keyboard)
    else:
        await message.answer(f"Переведите на английский: **{question}**", parse_mode="Markdown", reply_markup=keyboard)

@dp.message(QuizStates.ENGLISH_TO_RUSSIAN)
async def check_eng_to_rus(message: Message, state: FSMContext):
    # Check if message is a command
    if message.text.startswith('/'):
        return

    # Get data
    data = await state.get_data()
    correct_answer = data.get("correct_answer")
    correct_answer_lower = data.get("correct_answer_lower")

    # Check answer (без учета регистра)
    if message.text.lower() == correct_answer_lower:
        await message.answer("✅ Верно!")
        await state.update_data(correct_answers=data.get("correct_answers", 0) + 1)
    else:
        await message.answer(f"❌ Неправильно. Правильный ответ: {correct_answer}")

    # Move to next question
    await state.update_data(current_question=data.get("current_question", 0) + 1)
    await send_next_question(message, state)

@dp.message(QuizStates.RUSSIAN_TO_ENGLISH)
async def check_rus_to_eng(message: Message, state: FSMContext):
    # Check if message is a command
    if message.text.startswith('/'):
        return

    # Get data
    data = await state.get_data()
    correct_answer = data.get("correct_answer")
    correct_answer_lower = data.get("correct_answer_lower")

    # Check answer (без учета регистра)
    if message.text.lower() == correct_answer_lower:
        await message.answer("✅ Верно!")
        await state.update_data(correct_answers=data.get("correct_answers", 0) + 1)
    else:
        await message.answer(f"❌ Неправильно. Правильный ответ: {correct_answer}")

    # Move to next question
    await state.update_data(current_question=data.get("current_question", 0) + 1)
    await send_next_question(message, state)

async def main():
    logging.basicConfig(level=logging.INFO)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
