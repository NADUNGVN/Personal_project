from kokoro import KPipeline
import soundfile as sf
import sys

def main():
    try:
        # Load English ('a' = American, 'b' = British)
        print("Initializing Kokoro pipeline...")
        pipeline = KPipeline(lang_code='a')
        
        text = "Hello there! This is a test using Kokoro. Do you hear me fine?"
        
        print("Generating audio...")
        # Generating using American female voice 'af_bella'
        # Other voices are downloaded on the fly if needed
        generator = pipeline(
            text, voice='af_bella',
            speed=1, split_pattern=r'\n+'
        )
        
        for i, (gs, ps, audio) in enumerate(generator):
            if audio is not None:
                filename = f"kokoro_test_output_{i}.wav"
                sf.write(filename, audio, 24000)
                print(f"[{i}] Generated audio and saved to {filename}")
                print(f"[{i}] Graphemes: {gs}")
                print(f"[{i}] Phonemes: {ps}")
                print("-" * 30)
        
        print("Kokoro test completed successfully!")
    except Exception as e:
        print(f"Error while running Kokoro: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
