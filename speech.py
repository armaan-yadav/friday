#speech.py
from kokoro import KPipeline
import soundfile as sf

def main():
    # Initialize pipeline (American English)
    pipeline = KPipeline(lang_code='a')

    text = """
    Hello! This is a test of Kokoro text to speech running locally.
    If you can hear this, everything is working perfectly.
    """

    print("Generating speech...")

    # Generate audio chunks
    for i, (_, _, audio) in enumerate(pipeline(text, voice='af_heart')):
        output_file = f"output_{i}.wav"
        sf.write(output_file, audio, 24000)
        print(f"Saved: {output_file}")

    print("Done.")

if __name__ == "__main__":
    main()