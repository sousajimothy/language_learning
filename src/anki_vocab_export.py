import os

import json
import pandas as pd
from datetime import datetime

from openai import OpenAI


# --- CONFIGURATION ---

# IMPORTANT: Set your API key as an environment variable for security.
# In Windows (Command Prompt): set OPENAI_API_KEY=your_key_here
# In macOS/Linux (Terminal): export OPENAI_API_KEY='your_key_here'
# Or, you can hardcode it for simplicity, but it's not recommended:
# api_key = "sk-..." 
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# -------------------------------------------------- #
# Get current date and time
curr_dttm = datetime.now()
str_curr_dttm = curr_dttm.strftime("%Y-%m-%d_%H-%M")

print(str_curr_dttm)

output_file_path = rf"..\output"
output_tsv_name = rf"{str_curr_dttm}_anki_vocab_export"
output_xlsx_name = rf"{str_curr_dttm}_full_vocab_export"

output_tsv_path = os.path.join(output_file_path, f"{output_tsv_name}.tsv")
output_xlsx_path = os.path.join(output_file_path, f"{output_xlsx_name}.xlsx")




# --- SCRIPT LOGIC ---

def clean_text(raw_text):
    """Splits a multi-line string into a clean list of phrases."""
    # 1. Split the string into a list of lines
    lst_lines = raw_text.splitlines()

    # 2. Strip whitespace from each line and remove any empty lines
    lst_phrases_clean = [line.strip() for line in lst_lines if line.strip()]

    return lst_phrases_clean


def get_vocabulary_data(phrases_list):
    """Calls the OpenAI API to get structured data for a list of phrases."""
    
    system_prompt = """
    You are an expert German language tutor and data processor. The user will provide a list of German phrases or words.
    Your task is to process each item and return a single JSON object. The JSON object should contain one key, "vocabulary", which is a list of objects.
    Each object in the list must contain the following five keys: "deutsch", "deutsch_mit_artikel", "englisch", "afrikaans", and "hinweise".

    - `deutsch`: The original German phrase.
    - `deutsch_mit_artikel`: If the phrase contains a noun that needs an article, add it (e.g., "Kürbis" -> "der Kürbis"). For full sentences or non-nouns, this can be the same as the "deutsch" field.
    - `englisch`: The English translation.
    - `afrikaans`: The Afrikaans translation.
    - `hinweise`: The part of speech (Wortart), gender (Genus) for nouns, and any other helpful notes.

    Do not include any other text, explanations, or markdown formatting outside of the final JSON object.
    """

    # We format the list of phrases into a single string for the user message
    user_content = "\n".join(phrases_list)
    
    print("Sending data to the API...")
    try:
        response = client.chat.completions.create(
            # Using gpt-4o as it's powerful and cost-effective. gpt-3.5-turbo is faster/cheaper.
            model="gpt-4o", 
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            # This forces the model to return valid JSON
            response_format={"type": "json_object"} 
        )
        
        # The API returns a JSON string in the 'content' field
        response_data = json.loads(response.choices[0].message.content)
        print("Successfully received and parsed data from API.")
        return response_data['vocabulary']

    except Exception as e:
        print(f"An error occurred: {e}")
        return None

# The raw text copied from Microsoft Teams
raw_text = """

bis zum Monatsende

ich habe das Programm erweitert
 
hochladen 

die ihr beide sprechen könnt


ich habe den Code geändert
 
überprüfen 
 
es erlaubt einem, eine Antwort von Chat GPT direkt im Programm zu bekommen
 
Viele solche Dinge passieren auch mit...
 
Sicherheitslücke
 
du kannst nicht nur die Tür öffnen, sondern auch den Motor zünden
 
"Den Motor zünden" bedeutet, das Kraftstoff-Luft-Gemisch im Motor zu entzünden, damit er seine Arbeit aufnehmen kann.
 
den Motor einschalten 
 
es ist in Mode, größere Autos zu kaufen 
 

Schrebergärten 
 
Elendshütten 
 
seit ihrer Kindheit
 
aufgewertet/ abgewertet werden 
 
etwas anzünden: Feuer machen
 
den Motor zünden: den Motor einschalten 
 
das Tor ist verschlossen 
 
sie schlagen die Fenster ein 
 
die Fenster zerbrechen 
 
geklaut/ gestohlen 
 
er wurde überfallen 
 
die Autobahn, die Autobahnen (PL) 
 
S-Bahn 
 
sie streiken 
 
Uber nimmt mehr als 50% Provision 
 
besorgt
 
sie sind aufdringlich 
 
er hat diese Nummer abgezogen 
 
er hat sich genauso verhalten 
 
ich habe einen Freund, der Muslim ist
 
zur Viktorianischen Ära
 
die Waden 
 
die Knöchel 
 
unterhalb des Nackens/ Halses
 

"""



# --- EXECUTION ---

df = None # Initialize df to None

# Check if the output Excel file already exists
print(f"Checking for existing file: {output_xlsx_path}")

if os.path.exists(output_xlsx_path):
    # If it exists, load data from it and skip the API call
    print(f"✅ Found existing file. Loading data from '{output_xlsx_path}'.")
    print("--> To re-run the API call, please delete this file first. <---")
    df = pd.read_excel(output_xlsx_path)

else:

    # If the file does not exist, run the API call to get new data
    print("ℹ️ No cached file found. Calling the API to process new data...")

    # ------------------------------------------------- #
    # -- 01. Clean the raw text input ----------------- #
    # ------------------------------------------------- #
    phrases_to_process = clean_text(raw_text)
    print(f"Cleaned phrases to process: {len(phrases_to_process)}")

    # ------------------------------------------------- #
    # -- 02. Get the enriched data from the API ------- #
    # ------------------------------------------------- #
    vocabulary_list = get_vocabulary_data(phrases_to_process)

    if vocabulary_list:
        # ------------------------------------------------- #
        # -- 03. Load the data into a Pandas DataFrame ---- #
        # ------------------------------------------------- #
        df = pd.DataFrame(vocabulary_list)

        # ------------------------------------------------- #
        # -- Rename fields to match original Excel file --- #
        # ------------------------------------------------- #
        df.rename(columns={
            'deutsch': 'Deutsch',
            'deutsch_mit_artikel': 'Deutsch mit Artikel',
            'afrikaans': 'Afrikaans',
            'englisch': 'Englisch',
            'hinweise': 'Wortart / Genus / Hinweise',
        }, inplace=True)

        # ************************************************** #
        # -- [SAVE] Excel file with all vocabulary data ---- #
        # ************************************************** #
        df.to_excel(output_xlsx_path, index=False)
        print(f"✅ Full vocabulary export saved to Excel: {output_xlsx_path}")

# -------------------------------------------------- #
# --- Data Prep for Anki --------------------------- #
# -------------------------------------------------- #
if df is not None and not df.empty:
    # Prepare the Anki DataFrame

    df["Front"] = df["Deutsch mit Artikel"]
    df["Back"] = \
        df["Englisch"].fillna("") \
        + " — " \
        + df["Wortart / Genus / Hinweise"].fillna("")
    
    # -------------------------------------------------- #
    # -- 05. Only keep the relevant columns for Anki --- #
    # -------------------------------------------------- #
    anki_df = df[["Front", "Back"]]

    # ************************************************** #
    # -- [SAVE] TSV, ready for Anki import ------------- #
    # ************************************************** #
    anki_df.to_csv(
        output_tsv_path, 
        sep="\t", 
        index=False, 
        header=False,
        encoding='utf-8', # Good practice for special characters
    )

    print(f"✅ Anki TSV export created successfully: {output_tsv_path}")
    print("\nPreview of the first 5 rows:")
    print(anki_df.head())

else:
    print("❌ No data available to process for Anki.")