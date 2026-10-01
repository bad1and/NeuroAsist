# Локальный STT: сравнение на компьютере Romanov

Измерено 1 октября 2026 года. Лучший проверенный вариант по скорости при
сохранении текста — **GigaAM v3 RNNT, ONNX FP32, CUDA, 4 CPU-потока**.
На GTX 1660 SUPER запись длиной 130 секунд обработана за 2,39 секунды вместо
8,17 секунды у действующего PyTorch-провайдера. Нормализованные расшифровки
совпали во всех 35 случаях. Улучшение точности этим экспериментом не установлено.

При сравнении модели и дополнительные runtime-пакеты были подготовлены в
изолированной `.cache/stt-lab`, production STT тогда не переключался.
После выбора внедрён `gigaam_onnx`: ONNX FP32, `device=auto` с предпочтением
GPU и CPU-резервом. Рабочая `.venv` и локальная `.env` переключены; веса
перенесены в пользовательский каталог моделей. TeraTTS сохранён на CPU.
См. [настройки и зависимости](dependencies.md#gigaam-onnx-и-локальное-ускорение-stt).
При сравнении прошли 42 существующих теста voice/STT, проверки инструментов
и документации. Дополнительно проверены метрики, совпадение текстов и
фактическое наличие CUDA execution provider в полных GPU-отчётах.

## Проверка внедрения

После подключения к `VoiceService` прошёл 71 тест: новый provider, CUDA
initialization/inference recovery, отсутствие скрытого runtime fallback,
PCM/file paths, voice input, readiness и release settings. В реальном GPU-прогоне
с активной локальной конфигурацией все 35 сырых расшифровок совпали с baseline;
существующая коррекция терминов в VoiceService сохранена. CUDA оставалась
активной на всех файлах. 130,1 s распознаны за 2,63 s, 61,2 s — за 1,25 s,
33,1 s — за 0,65 s (медиана трёх повторов через сервис).

Также выполнены два smoke с настоящей ONNX CPU-моделью: искусственно отклонённая
CUDA initialization и отдельный процесс с CPU-only ONNX Runtime 1.23.2.
В обоих `auto` успешно выбрал CPU и распознал речь. Отчёты:
`output/stt-comparison/iris-integrated-gpu.json`, `iris-cpu-recovery.json`,
`iris-cpu-only-runtime.json`. Зависимости GPU установлены в рабочую `.venv`,
веса скопированы из проверенной лаборатории в пользовательский каталог.

Полная desktop-сборка и ручной разговор с микрофоном не выполнялись.
Общий аудит старой developer `.venv` не проходит из-за отсутствующего
`sentence-transformers` и прежних расхождений `regex` / `safetensors` с
constraints; CUDA/STT пакеты установлены в выбранных версиях. `pip check`
также видит старые конфликтующие TTS-эксперименты и номинальное отсутствие
CPU distribution `onnxruntime` при установленном GPU runtime. Эти проверки
не представлены как успешно прошедшие.

## Условия и методика

- Ryzen 7 5700X, 8 ядер / 16 потоков, 31,93 GiB RAM; GTX 1660 SUPER, 6 GiB VRAM,
  NVIDIA driver 616.92; Windows, Python из `.venv` проекта.
- Baseline: фактический `GigaAMSTTProvider`, `v3_rnnt`, PyTorch 2.11.0+cpu,
  4 intra-op / 1 inter-op поток. ONNX: ONNX Runtime 1.23.2, onnx-asr 0.12.0.
  Потоковые модели: sherpa-onnx 1.13.8, CPU, 4 потока.
- 24 записи человеческой русской речи из test-набора Russian LibriSpeech:
  по 4 записи с offsets 0, 200, 400, 600, 800, 1000. Это чтение литературы,
  ограниченная выборка глав/дикторов, без записей голоса пользователя.
- Отдельно 8 синтетических фраз `TeraTTSv2 / ru_f1` из локального listening pack.
  Они проверяют термины и сложный текст; их WER не смешивается с человеческой речью.
- Три длинных replay собраны из целых публичных записей с паузой 200 ms между
  фрагментами. Длительности с pre-roll: 33,1 / 61,2 / 130,1 секунды. Это проверка
  обработки длинного входа, а не три новых независимых диктора.
- Общий pre-roll 900 ms. У потоковых моделей при остановке добавлен локальный
  zero-padding 1000 ms, затем `input_finished`; дополнительную секунду ожидания
  этот padding не создаёт. Batch-модели используют исходное аудио с pre-roll.
- После прогрева: медиана 3 повторов каждого файла. Nemotron и тесты с фоновой
  нагрузкой — 1 повтор, предварительное сравнение. Конфигурации запускались
  последовательно. Загрузка модели измерена отдельно, в таблицы не входит.
- WER: суммарное число вставок, удалений и замен / число слов reference;
  регистр, пунктуация и различие `ё/е` игнорируются. P95 — nearest-rank, поэтому
  для трёх длинных записей это максимум. Текст каждой записи сохранён в JSON.
- ONNX повторяет текущие quiet cuts, overlap 0,75 s и merge GigaAM, чтобы
  сравнивать движки при одинаковом разбиении длинного входа.
- Tail для batch равен времени обработки после остановки. Для streaming это
  **оценка replay с виртуальными моментами прихода PCM-фреймов**, учитывающая
  очередь вычислений. Реальные VAD, Smart Turn, браузер, WebSocket, LLM и TTS
  в эти времена не входят. Это не замер полной задержки диалога.

## Результаты

Времена в миллисекундах; WER меньше — лучше. Streaming tail следует читать
с оговоркой о replay выше. Последний столбец — полный compute длинной записи,
включая вычисления во время речи у streaming.

| Модель / runtime | WER, человек | WER, длинные | P95 tail, человек | P95 tail, длинные | Compute 130 s |
| --- | ---: | ---: | ---: | ---: | ---: |
| GigaAM RNNT PyTorch CPU 4, baseline | 4,12% | 2,17% | 913 | 8170 | 8170 |
| **GigaAM RNNT ONNX FP32 CUDA 4** | **4,12%** | **2,17%** | **236** | **2386** | **2386** |
| GigaAM RNNT ONNX FP32 CPU 8 | 4,12% | 2,17% | 325 | 3424 | 3424 |
| GigaAM RNNT ONNX FP32 CPU 4 | 4,12% | 2,17% | 459 | 4538 | 4538 |
| GigaAM RNNT ONNX FP32 CPU 2 | 4,12% | 2,17% | 771 | 7355 | 7355 |
| GigaAM RNNT ONNX INT8 CPU 4 | 4,12% | 3,26% | 460 | 4295 | 4295 |
| GigaAM CTC ONNX FP32 CPU 4 | 5,88% | 3,04% | 420 | 3985 | 3985 |
| GigaAM CTC ONNX INT8 CPU 4 | 5,88% | 4,13% | 418 | 4041 | 4041 |
| T-one streaming CPU 4 | 5,59% | 4,78% | 59 | 53 | 6212 |
| Nemotron streaming INT8 160 ms CPU 4 | 23,82% | 18,26% | 469 | 425 | 53315 |
| Nemotron streaming INT8 560 ms CPU 4 | 24,12% | 20,43% | 170 | 155 | 18790 |
| Nemotron streaming INT8 1120 ms CPU 4 | 19,71% | 20,87% | 112 | 124 | 13277 |

GPU ускорил самый длинный вход в 3,42 раза, CPU 8 — в 2,39 раза.
Все FP32 RNNT-конфигурации, включая GPU и фоновую нагрузку, дали одинаковые
нормализованные тексты с baseline на 35/35 записях. INT8 RNNT изменил 7/35
текстов, включая длинные: экономия памяти не прошла условие сохранения качества.
CTC, T-one и проверенные экспорты Nemotron также не прошли это условие.
Это вывод о конкретных конфигурациях и выборке, не рейтинг моделей для всей
русской речи. Немотрон проверен с `language=ru`, feature dimension 128.

На синтетических фразах WER baseline и FP32 RNNT — 22,39%; INT8 RNNT — 20,90%,
T-one — 22,39%; Nemotron 160/560/1120 — 23,88 / 20,90 / 25,37%.
Высокий WER здесь дополнительно показывает, что литературная речь не заменяет
проверку разговорного русского, имён и терминов на личном микрофоне.

### Длинный вход и ресурсы победителя

| Длительность | Baseline CPU 4 | ONNX FP32 CUDA 4 | ONNX FP32 CPU 8 |
| --- | ---: | ---: | ---: |
| 33,1 s | 2038 ms | 714 ms | 938 ms |
| 61,2 s | 3742 ms | 1135 ms | 1549 ms |
| 130,1 s | 8170 ms | 2386 ms | 3424 ms |

Наблюдаемый RSS процесса после файлов: baseline 1788 MiB; ONNX GPU 899 MiB;
ONNX CPU 8 — 1097 MiB; INT8 RNNT CPU — 408 MiB. Это снимки памяти, не непрерывный
профиль пиков внутри inference. Для GPU максимум снимков `nvidia-smi` —
3861 MiB **всего устройства**, включая desktop и другие процессы; это не
изолированная VRAM модели. Загрузка победителя — около 1,64 s в тёплом файловом
кэше. GPU успешно обработал все файлы без аварийного переключения на CPU.
Часть служебных узлов графа и preprocessing закономерно остаются на CPU.

Дополнительный прогон с тремя независимыми CPU arithmetic workers, 1 повтор:

| Конфигурация | P95, человек | 130,1 s | Совпадение текста с baseline |
| --- | ---: | ---: | ---: |
| ONNX FP32 CPU 4 | 487 ms | 4762 ms | 35/35 |
| ONNX FP32 CUDA 4 | 285 ms | 2578 ms | 35/35 |

Это проверка конкуренции за CPU, не игровой benchmark и не проверка
одновременного запуска Unity / TeraTTS / GPU-игры. Для такого режима разумный
резерв — ONNX FP32 CPU 8; конкретный баланс потоков нужно проверить вместе
с реальной нагрузкой приложения.

## Воспроизведение

[Подготовка данных](../scripts/prepare_stt_lab.py) скачивает модели и публичный
корпус в `.cache/stt-lab`, ничего не загружая наружу.
[Benchmark](../scripts/benchmark_local_stt.py) создаёт отдельный JSON с
конфигурацией, reference, transcript, WER, временем и ресурсами.
Модели и результаты в `.cache/` / `output/` не включены в Git.

Из корня репозитория, с существующей `.venv` Iris:

```powershell
.\.venv\Scripts\python.exe -m pip install --no-deps --target .cache/stt-lab/site onnx-asr==0.12.0 sherpa-onnx==1.13.8 sherpa-onnx-core==1.13.8
.\.venv\Scripts\python.exe scripts/prepare_stt_lab.py

$sttCommon = @('--manifest', '.cache/stt-lab/corpus/manifest.json', '--include-long', '--pre-roll-ms', '900', '--padding-ms', '1000', '--site-packages', '.cache/stt-lab/site')
.\.venv\Scripts\python.exe scripts/benchmark_local_stt.py @sttCommon --engine gigaam --model v3_rnnt --output output/stt-comparison/baseline.json
.\.venv\Scripts\python.exe scripts/benchmark_local_stt.py @sttCommon --engine onnx --model gigaam-v3-rnnt --model-dir .cache/stt-lab/models/gigaam-v3 --threads 8 --output output/stt-comparison/cpu8.json
```

Добавить `--include-synthetic` можно при наличии локального TeraTTS listening
pack. Для CTC заменить model на `gigaam-v3-ctc`; INT8 — `--quantization int8`.
Для native streaming использовать `--engine sherpa --model t-one` или
`--model nemotron` и соответствующую папку модели из подготовки. Nemotron
в этом сравнении запускался с `--repeats 1`, остальные основные прогоны — 3.

GPU-пакеты установлены отдельно от CPU ONNX Runtime. На этой видеокарте
cuDNN 9.27.0.42 не выполнил convolution frontend; рабочая версия — 9.10.2.21.
Benchmark проверяет наличие CUDA в ASR sessions и отключает аварийный fallback,
чтобы ошибочный CPU-прогон не выдавался за GPU.

```powershell
.\.venv\Scripts\python.exe -m pip install --no-deps --target .cache/stt-lab/gpu-site onnxruntime-gpu==1.23.2 nvidia-cuda-runtime-cu12==12.9.79 nvidia-cublas-cu12==12.9.2.10
.\.venv\Scripts\python.exe -m pip install --no-deps --target .cache/stt-lab/cufft-site nvidia-cufft-cu12==11.4.1.4
.\.venv\Scripts\python.exe -m pip install --no-deps --target .cache/stt-lab/cudnn-compat-site nvidia-cudnn-cu12==9.10.2.21
$sttPreviousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = (Resolve-Path .cache/stt-lab/gpu-site).Path + ';' + (Resolve-Path .cache/stt-lab/cufft-site).Path
    .\.venv\Scripts\python.exe scripts/benchmark_local_stt.py @sttCommon --engine onnx --model gigaam-v3-rnnt --model-dir .cache/stt-lab/models/gigaam-v3 --device cuda --cudnn-dir .cache/stt-lab/cudnn-compat-site/nvidia/cudnn/bin --output output/stt-comparison/gpu.json
} finally {
    $env:PYTHONPATH = $sttPreviousPythonPath
}
```

На диске сохранены фактические отчёты `output/stt-comparison/*.json`, в частности
`gigaam-rnnt-torch-t4.json`, `gigaam-rnnt-onnx-fp32-cuda-t4.json` и
`gigaam-rnnt-onnx-fp32-t8.json`. Старый пробный `.cache/stt-lab/gpu-smoke.json`
получен с CPU fallback и исключён из выводов; успешный smoke и полные GPU-прогоны
проведены с совместимым cuDNN и контролем execution providers.

Для личного корпуса создать JSON-список и передать его через `--manifest`:

```json
[
  {"audio": "voice-01.wav", "reference": "Точно записанный текст фразы", "tags": ["public", "personal"]}
]
```

Пути относительны manifest. Здесь `public` — техническое имя агрегата benchmark,
не разрешение публикации: локальные записи никуда не отправляются. Не добавлять
`--include-long` для короткого личного набора, если общей речи меньше 120 s.
Личная проверка нужна перед обещанием сохранения качества в реальном диалоге.
Текущий победитель остаётся batch STT; обработку во время речи потребуется
отдельно интегрировать в PCM pipeline. Этот эксперимент не реализует live UI.

## Происхождение моделей и данных

- [GigaAM v3 ONNX](https://huggingface.co/istupakov/gigaam-v3-onnx), revision
  `322c3b29492673eb7d0b434bfa9dfb8653e34d02`; RNNT encoder/decoder/joint,
  CTC и INT8 экспорты. [Авторское сравнение onnx-asr](https://github.com/istupakov/onnx-asr/blob/main/docs/comparison.md)
  использовано для отбора кандидатов; приведённые выше цифры измерены здесь.
- [Russian LibriSpeech](https://huggingface.co/datasets/istupakov/russian_librispeech),
  revision `a519c986bb3342cc8136d3d14e5ad8a4f1e1a2bd`.
- [Nemotron streaming exports](https://k2-fsa.github.io/sherpa/onnx/nemo/nemotron-streaming.html):
  release `asr-models`, архивы `sherpa-onnx-nemotron-3.5-asr-streaming-0.6b-{160,560,1120}ms-int8-2026-06-11`;
  [исходная модель NVIDIA](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b).
- [T-one](https://github.com/voicekit-team/T-one): release `asr-models`, архив
  `sherpa-onnx-streaming-t-one-russian-2025-09-08`. Это sherpa CTC export,
  без отдельного внешнего языкового декодера.
- [ONNX Runtime CUDA dependencies](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html),
  [cuDNN 9.10.2 release notes](https://docs.nvidia.com/deeplearning/cudnn/backend/v9.10.2/release-notes.html).

Qwen ASR, Whisper и облачные API в измеренную таблицу не включены.
Название «лучший» относится к проверенным здесь локальным конфигурациям.
