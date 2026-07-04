import logging
import os
import time

logger = logging.getLogger(__name__)

_model = None
_model_name = os.getenv("CE_WHISPER_MODEL", "tiny")


def _save_transcript(transcript: str) -> str:
    output_path = os.path.join("output", "transcript.txt")
    os.makedirs("output", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(transcript)
    return transcript


def _transcribe_openai(file_path: str) -> str:
    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is required when CE_TRANSCRIBE_MODE=openai.")

    client = OpenAI(api_key=api_key)
    model = os.getenv("CE_OPENAI_WHISPER_MODEL", "whisper-1")

    with open(file_path, "rb") as audio_file:
        result = client.audio.transcriptions.create(model=model, file=audio_file)

    return _save_transcript(result.text.strip())


def _transcribe_local(file_path: str) -> str:
    start = time.perf_counter()
    model = _get_model()

    result = model.transcribe(
        file_path,
        fp16=False,
        verbose=False,
    )
    transcript = result["text"].strip()

    elapsed = time.perf_counter() - start
    logger.info("Local transcription done in %.1fs (%d chars)", elapsed, len(transcript))

    return _save_transcript(transcript)


def _get_model():
    global _model
    if _model is None:
        import whisper

        logger.info("Loading Whisper model: %s", _model_name)
        _model = whisper.load_model(_model_name)
    return _model


def transcribe_audio(file_path: str) -> str:
    mode = os.getenv("CE_TRANSCRIBE_MODE", "local").lower()
    start = time.perf_counter()

    if mode == "openai":
        logger.info("Transcribing via OpenAI API")
        transcript = _transcribe_openai(file_path)
    else:
        logger.info("Transcribing via local Whisper")
        transcript = _transcribe_local(file_path)

    logger.info("Transcription finished in %.1fs (%d chars)", time.perf_counter() - start, len(transcript))
    return transcript
