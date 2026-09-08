"""Диагностика vision-моделей Groq. Запускать отдельно от бота."""
import asyncio, base64, os, sys
from pathlib import Path
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

client = AsyncOpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1",
)

# ── 1. Список доступных моделей ────────────────────────────────────────────
async def list_models():
    print("\n=== Доступные модели Groq ===")
    models = await client.models.list()
    vision = []
    for m in sorted(models.data, key=lambda x: x.id):
        print(" ", m.id)
        if "vision" in m.id or "llava" in m.id or "scout" in m.id or "maverick" in m.id:
            vision.append(m.id)
    print(f"\nПотенциальные vision-модели: {vision}")
    return vision

# ── 2. Тест vision с маленькой картинкой ──────────────────────────────────
async def test_vision(model: str):
    # Минимальный 1x1 белый JPEG в base64 для теста API
    tiny_jpeg_b64 = (
        "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8U"
        "HRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgN"
        "DRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
        "MjL/wAARCAABAAEDASIAAhEBAxEB/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAA"
        "AAAAAAAAAAAAAP/EABQBAQAAAAAAAAAAAAAAAAAAAAD/xAAUEQEAAAAAAAAAAAAAAAAAAAAA"
        "/9oADAMBAAIRAxEAPwCwABmX/9k="
    )

    print(f"\n=== Тест модели: {model} ===")
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{tiny_jpeg_b64}"}},
                    {"type": "text", "text": "Опиши что видишь на изображении. Ответь одним предложением."},
                ],
            }],
            max_tokens=100,
        )
        print("  УСПЕХ:", resp.choices[0].message.content)
        return True
    except Exception as e:
        print(f"  ОШИБКА: {e}")
        return False


async def test_url_vision():
    """Тест llama-4-scout с публичным URL картинки."""
    model = "meta-llama/llama-4-scout-17b-16e-instruct"
    test_url = "https://upload.wikimedia.org/wikipedia/commons/thumb/4/47/PNG_transparency_demonstration_1.png/240px-PNG_transparency_demonstration_1.png"
    print(f"\n=== Тест URL-режима: {model} ===")
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": test_url}},
                    {"type": "text", "text": "Опиши что видишь. Одно предложение."},
                ],
            }],
            max_tokens=100,
        )
        print("  УСПЕХ:", resp.choices[0].message.content)
        return True
    except Exception as e:
        print(f"  ОШИБКА: {e}")
        return False


async def main():
    vision_models = await list_models()
    models_to_test = list(set(vision_models + [
        "llama-3.2-11b-vision-preview",
        "llama-3.2-90b-vision-preview",
        "meta-llama/llama-4-scout-17b-16e-instruct",
    ]))
    working = []
    for m in models_to_test:
        ok = await test_vision(m)
        if ok:
            working.append(m)

    # Отдельно тест через URL
    await test_url_vision()

    print("\n" + "="*50)
    if working:
        print(f"✅ Рабочие vision-модели: {working}")
    else:
        print("❌ base64 не работает ни для одной модели.")

asyncio.run(main())
