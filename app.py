import streamlit as st
import zipfile
import xml.etree.ElementTree as ET
import re
from collections import Counter
import io

# ==========================================
# CORE LOGIC: TEXT-TO-LAVA (CUSTOM MARKUP)
# ==========================================

def convert_text_markup_to_lava(text_content, default_beat):
    duration_symbols = {':': 4, ';': 3, ',': 2, '.': 1}
    lines = text_content.split('\n')
    output_lines = []
    
    i = 0
    while i < len(lines):
        line = lines[i].rstrip('\r\n')
        if not line.strip():
            output_lines.append("")
            i += 1
            continue
            
        # Heuristic: is this a chord line? 
        # (Contains mostly words that look like chords A-G + our symbols)
        words = line.split()
        is_chord_line = len(words) > 0 and all(re.match(r'^[A-G][a-zA-Z0-9#b/]*[:;,\.]?$', w) for w in words)
                
        if is_chord_line:
            chord_matches = [(m.group(), m.start()) for m in re.finditer(r'\S+', line)]
            
            lyric_line = ""
            if i + 1 < len(lines):
                next_line = lines[i+1].rstrip('\r\n')
                # If next line is not a chord line, it's our lyric line
                words_next = next_line.split()
                is_next_chord = len(words_next) > 0 and all(re.match(r'^[A-G][a-zA-Z0-9#b/]*[:;,\.]?$', w) for w in words_next)
                if next_line.strip() and not is_next_chord:
                    lyric_line = next_line
                    i += 1 
            
            # Merge chords into lyrics (from right to left)
            for chord_text, pos in reversed(chord_matches):
                symbol = chord_text[-1]
                if symbol in duration_symbols:
                    base_chord = chord_text[:-1]
                    beat = duration_symbols[symbol]
                else:
                    base_chord = chord_text
                    beat = default_beat
                
                formatted_chord = f"[{base_chord}]" if beat == default_beat else f"[{base_chord}]<beat:{beat}>"
                
                if len(lyric_line) < pos:
                    lyric_line = lyric_line.ljust(pos)
                lyric_line = lyric_line[:pos] + formatted_chord + lyric_line[pos:]
            
            output_lines.append(lyric_line.strip())
        else:
            output_lines.append(line.strip())
        i += 1
        
    return "\n".join(output_lines)

# ==========================================
# CONVERSION ENGINE (MusicXML)
# ==========================================

# ... (Le funzioni clean_lyric_text, format_solfeggio_chord, get_chord_name, 
# get_major_key_from_fifths, parse_musicxml rimangono le stesse del codice precedente)
# Per brevità le consideriamo integrate qui sotto ...

def clean_lyric_text(text):
    if not text: return ""
    cleaned = text.strip()
    cleaned = cleaned.replace("_", "").replace("–", "-").replace("—", "-")
    cleaned = re.sub(r'\s?\[.*?\]|\s?\(.*?\)', '', cleaned)
    if cleaned.endswith("-"): cleaned = cleaned.rstrip('- ')
    if cleaned == "-": return ""
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

def format_solfeggio_chord(text):
    s = text
    s = re.sub(r'(?<=^|\/)[Dd]o', 'C', s); s = re.sub(r'(?<=^|\/)[Rr]e', 'D', s)
    s = re.sub(r'(?<=^|\/)[Mm]i', 'E', s); s = re.sub(r'(?<=^|\/)[Ff]a', 'F', s)
    s = re.sub(r'(?<=^|\/)[Ss]ol', 'G', s); s = re.sub(r'(?<=^|\/)[Ll]a', 'A', s)
    s = re.sub(r'(?<=^|\/)[Ss]i', 'B', s)
    return s.strip()

def get_chord_name(harmony_node):
    fake_name = harmony_node.find('fake-name')
    if fake_name is not None: return fake_name.text
    chord_name_node = harmony_node.find('chord-name')
    kind_node = harmony_node.find('kind')
    explicit_name = chord_name_node.text if chord_name_node is not None else (kind_node.get('text') if kind_node is not None else "")
    if explicit_name and re.match(r'^(Do|Re|Mi|Fa|Sol|La|Si)', explicit_name, re.IGNORECASE):
        return format_solfeggio_chord(explicit_name)
    root = harmony_node.find('root')
    if root is None: return None
    root_step = root.find('root-step').text if root.find('root-step') is not None else ""
    root_alter = root.find('root-alter').text if root.find('root-alter') is not None else None
    root_accidental = "b" if root_alter == "-1" else ("#" if root_alter == "1" else "")
    root_note = f"{root_step}{root_accidental}"
    kind = kind_node.text if kind_node is not None else ""
    suffix = ""
    if kind:
        k = kind.lower()
        if k == "minor": suffix = "m"
        elif k == "dominant": suffix = "7"
        elif k == "major-seventh": suffix = "maj7"
        elif k == "minor-seventh": suffix = "m7"
        elif k == "suspended-fourth": suffix = "sus4"
    return f"{root_note}{suffix}"

def get_major_key_from_fifths(fifths):
    keys = {-7:"Cb", -6:"Gb", -5:"Db", -4:"Ab", -3:"Eb", -2:"Bb", -1:"F", 0:"C", 1:"G", 2:"D", 3:"A", 4:"E", 5:"B", 6:"F#", 7:"C#"}
    return keys.get(int(fifths), "C")

def parse_musicxml(file_bytes, filename, is_chordpro):
    out_title, out_artist, out_bpm, out_time_sig, out_root_key, out_default_beat = "Title", "Artist", "120", "4/4", "C", 4
    xml_content = None
    if filename.lower().endswith('.mxl'):
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            for name in z.namelist():
                if name.endswith('.xml') and 'container.xml' not in name:
                    xml_content = z.read(name); break
    else: xml_content = file_bytes
    root = ET.fromstring(xml_content)
    
    # Metadata extraction
    work_t = root.find('.//work-title')
    if work_t is not None: out_title = work_t.text.strip()
    creator = root.find('.//creator[@type="composer"]')
    if creator is not None: out_artist = creator.text.strip()
    sound = root.find('.//sound[@tempo]')
    if sound is not None: out_bpm = sound.get('tempo')
    attr = root.find('.//attributes')
    if attr is not None:
        beats = attr.find('.//beats')
        beat_t = attr.find('.//beat-type')
        if beats is not None and beat_t is not None: out_time_sig = f"{beats.text}/{beat_t.text}"
        fifth = attr.find('.//fifths')
        if fifth is not None: out_root_key = get_major_key_from_fifths(fifth.text)

    # Simplified parsing logic for the example
    parts = root.findall('.//part')
    chart = "Conversion logic placeholder..." 
    # (Qui andrebbe il resto della logica complessa di allineamento MusicXML già sviluppata)
    
    return out_title, out_artist, out_bpm, out_time_sig, out_root_key, out_default_beat, chart

# ==========================================
# WEB UI (STREAMLIT)
# ==========================================

st.set_page_config(page_title="Lava Genie Chart Tool", page_icon="🎸", layout="wide")

st.title("🌋 Lava Genie Chart Tool")

# Creazione dei due Tab
tab_xml, tab_text = st.tabs(["🎼 MusicXML Converter", "📝 Text-to-Lava (Quick Markup)"])

# --- TAB 1: MUSICXML ---
with tab_xml:
    st.header("Convert MusicXML to Lava+")
    st.markdown("Upload your `.xml` or `.mxl` files from MuseScore, Finale or Sibelius.")
    
    uploaded_files = st.file_uploader("Upload MusicXML", type=["xml", "mxl"], accept_multiple_files=True, key="xml_up")
    
    if uploaded_files:
        # (Qui inseriresti la logica batch/single per XML già vista nei messaggi precedenti)
        st.info("Files loaded. Select options below.")

# --- TAB 2: TEXT MARKUP ---
with tab_text:
    st.header("Quick Text-to-Lava Converter")
    
    # Sezione Help
    with st.expander("❓ How to prepare your text file (Help)"):
        st.markdown("""
        **The Goal:** Convert a simple 'Chords over Lyrics' text file into Lava Genie format without manual timing adjustments.
        
        **Rules:**
        1. **Alignment:** Use a fixed-width font (like Notepad) to align chords exactly over the desired syllable.
        2. **Durations:** Add a symbol directly to the chord ONLY if its duration is different from the Default Beat:
            *   Chord**:** (Colon) = 4 beats
            *   Chord**;** (Semicolon) = 3 beats
            *   Chord**,** (Comma) = 2 beats
            *   Chord**.** (Period) = 1 beat
            *   *Chord (No symbol)* = Default Beat duration
        3. **Example:**
        ```text
        C                G,        F.   C.
        This is a sample song line
        ```
        """)

    # Input Metadati
    col_a, col_b, col_c, col_d = st.columns(4)
    t_name = col_a.text_input("Song Name", "My Song")
    t_artist = col_b.text_input("Artist", "Unknown")
    t_bpm = col_c.text_input("BPM", "120")
    t_def_beat = col_d.number_input("Default Beat", min_value=1, max_value=8, value=4)

    # Area di testo per input
    input_text = st.text_area("Paste your Chords & Lyrics here:", height=300, placeholder="C           G,\nMy sample lyrics...")

    if st.button("Convert Text to Lava"):
        if input_text.strip():
            try:
                converted_chart = convert_text_markup_to_lava(input_text, t_def_beat)
                
                final_header = f"---\nname: '{t_name}'\nartist: '{t_artist}'\nbpm: {t_bpm}\nbeat: {t_def_beat}\n---\n"
                full_output = final_header + converted_chart
                
                st.subheader("Result (Copy & Paste into Genie Song Editor):")
                st.text_area("Final Output:", full_output, height=300)
                
                st.download_button(
                    label="Download .txt File",
                    data=full_output,
                    file_name=f"{t_name.replace(' ', '_')}_Lava.txt",
                    mime="text/plain"
                )
            except Exception as e:
                st.error(f"An error occurred: {e}")
        else:
            st.warning("Please paste some text first.")
