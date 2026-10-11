<img src="../apps/web/public/brand/iris-mark-backed-dark.svg" width="36" alt="Знак Iris">

<sub>[Документация](index.md) / История</sub>

# Эксперимент Qwen3-TTS

**Исторический материал.** Qwen не устанавливается и не выбирается основным
ядром Iris. Текущий TTS — TeraTTSv2, голос `ru_f1`.
Silero используется для VAD. Этот файл сохранён для ссылок на исследование.

## Изоляция

Эксперимент использовал отдельное CUDA-окружение, `qwen-tts`,
revision `c27fe8aa05b732b1376d0f6a1e522fbccb84abbd`, `float16` и PyTorch SDPA.
FlashAttention и BF16 не требовались.
Пакеты не добавляются в основную `.venv` или профили установщика.

Голосовой reference и его точная расшифровка получаются отдельно с разрешением
на выбранный сценарий. Прежний `qwen-baya-neutral.wav` не распространяется
в репозитории. Инструкция не обещает воспроизводимость без этих данных и
проверенного изолированного окружения.

## Методика

[`benchmark_qwen_tts.py`](../scripts/benchmark_qwen_tts.py) проверяет
100 сегментов. Шаблон запуска с собственным разрешённым образцом:

```powershell
$qwenPython = 'C:\path\to\qwen-env\Scripts\python.exe'
$referenceWav = 'C:\path\to\approved-reference.wav'
& $qwenPython scripts/benchmark_qwen_tts.py `
  --python $qwenPython --reference-wav $referenceWav `
  --reference-text 'ТОЧНАЯ РАСШИФРОВКА ВАШЕГО ОБРАЗЦА'
```

Значения заменяются реальными путями и текстом.
После слепого сравнения 20 пар эксперимент повторяется с фактическими
`--blind-wins` и `--similarity-median`.
Отчёт `passed: false` не является основанием для включения провайдера.

## Граница исследования

Исторический план quality pack предполагал закреплённую revision,
SHA-256 всех файлов и отдельную проверку Model Manager.
Наличие benchmark-скрипта не означает наличие поддерживаемого production pack.

Продвижение эксперимента в продукт требует нового решения, лицензий весов и
образца, проверки памяти/скорости, воспроизведения и отмены.
Текущий TeraTTS-путь от запуска этого эксперимента не меняется.

---

[Зависимости](dependencies.md) · [Сторонние материалы](../THIRD_PARTY_ASSETS.md)
