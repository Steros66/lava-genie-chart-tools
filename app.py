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
    duration_symbols = {'!': 6, ':': 4, ';': 3, ',': 2, '.': 1}
    lines = text_content.split('\n')
    output_lines = []
    
    i = 0
    while i < len(lines):
        line = lines[i].rstrip('\r\n')
        if not line.strip():
            output_lines.append("")
            i += 1
            continue
            
        if re.search(r'\[(.*?)\]', line):
            def replace_inline_chord(match):
                chord_text = match.group(1).strip()
                if not chord_text: return "[]"
                
                symbol = chord_text[-1]
                if symbol in duration_symbols:
                    base_chord = chord_text[:-1]
                    beat = duration_symbols[symbol]
                else:
                    base_chord = chord_text
                    beat = default_beat
                
                if beat == default_beat:
                    return f"[{base_chord}]"
                else:
                    return f"[{base_chord}]<beat:{beat}>"
            
            converted_line = re.sub(r'\[(.*?)\]', replace_inline_chord, line)
            output_lines.append(converted_line.strip())
            i += 1
            continue

        words = line.split()
        is_chord_line = len(words) > 0 and all(re.match(r'^[A-G][a-zA-Z0-9#b/]*[:;,\.!]?$', w) for w in words)
                
        if is_chord_line:
            chord_matches = [(m.group(), m.start()) for m in re.finditer(r'\S+', line)]
            
            lyric_line = ""
            if i + 1 < len(lines):
                next_line = lines[i+1].rstrip('\r\n')
                words_next = next_line.split()
                is_next_chord = len(words_next) > 0 and all(re.match(r'^[A-G][a-zA-Z0-9#b/]*[:;,\.!]?$', w) for w in words_next)
                if next_line.strip() and not is_next_chord and not re.search(r'\[(.*?)\]', next_line):
                    lyric_line = next_line
                    i += 1 
            
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
        
    final_output = "\n".join(output_lines)
    final_output = re.sub(r'^{.*?}$', '', final_output, flags=re.MULTILINE) 
    
    return final_output.strip()

# ==========================================
# CONVERSION ENGINE (MusicXML)
# ==========================================

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
    s = re.sub(r'(?<=^|\/)[Dd]o', 'C', s)
    s = re.sub(r'(?<=^|\/)[Rr]e', 'D', s)
    s = re.sub(r'(?<=^|\/)[Mm]i', 'E', s)
    s = re.sub(r'(?<=^|\/)[Ff]a', 'F', s)
    s = re.sub(r'(?<=^|\/)[Ss]ol', 'G', s)
    s = re.sub(r'(?<=^|\/)[Ll]a', 'A', s)
    s = re.sub(r'(?<=^|\/)[Ss]i', 'B', s)
    return s.strip()

def get_chord_name(harmony_node):
    fake_name = harmony_node.find('fake-name')
    if fake_name is not None and fake_name.text: return fake_name.text.strip()

    chord_name_node = harmony_node.find('chord-name')
    kind_node = harmony_node.find('kind')
    
    explicit_name = (chord_name_node.text or "") if chord_name_node is not None else (kind_node.get('text') or "" if kind_node is not None else "")
    if explicit_name and re.match(r'^(Do|Re|Mi|Fa|Sol|La|Si)', explicit_name, re.IGNORECASE):
        return format_solfeggio_chord(explicit_name)

    root = harmony_node.find('root')
    if root is None: return None

    root_step = (root.find('root-step').text or "") if root.find('root-step') is not None else ""
    root_alter = (root.find('root-alter').text or "") if root.find('root-alter') is not None else None
    root_accidental = "b" if root_alter == "-1" else ("#" if root_alter == "1" else "")
    root_note = f"{root_step}{root_accidental}"

    kind = (kind_node.text or "") if kind_node is not None else ""
    kind_text_attr = kind_node.get('text') or "" if kind_node is not None else ""
    
    suffix = ""
    if kind_text_attr and kind_text_attr.lower() in ["add9", "sus9"]:
        suffix = kind_text_attr
    elif kind:
        kind_lower = kind.lower()
        if kind_lower == "minor": suffix = "m"
        elif kind_lower == "dominant": suffix = "7"
        elif kind_lower == "major-seventh": suffix = "maj7"
        elif kind_lower == "minor-seventh": suffix = "m7"
        elif kind_lower == "half-diminished": suffix = "m7b5"
        elif kind_lower == "major-ninth": suffix = "maj9"
        elif kind_lower == "minor-ninth": suffix = "m9"
        elif kind_lower == "dominant-ninth": suffix = "9"
        elif kind_lower == "suspended-fourth": suffix = "sus4"
        elif kind_lower == "suspended-second": suffix = "sus2"
        elif kind_lower == "diminished": suffix = "dim"
        elif kind_lower == "diminished-seventh": suffix = "dim7"
        elif "minor-seventh" in kind_lower: suffix = "m7"
        elif "minor" in kind_lower: suffix = "m"

    bass_note = ""
    bass = harmony_node.find('bass')
    if bass is not None:
        bass_step = (bass.find('bass-step').text or "") if bass.find('bass-step') is not None else ""
        bass_alter = (bass.find('bass-alter').text or "") if bass.find('bass-alter') is not None else None
        bass_accidental = "b" if bass_alter == "-1" else ("#" if bass_alter == "1" else "")
        if bass_step: bass_note = f"/{bass_step}{bass_accidental}"

    return f"{root_note}{suffix}{bass_note}"

def get_major_key_from_fifths(fifths):
    keys = {-7:"Cb", -6:"Gb", -5:"Db", -4:"Ab", -3:"Eb", -2:"Bb", -1:"F", 0:"C", 1:"G", 2:"D", 3:"A", 4:"E", 5:"B", 6:"F#", 7:"C#"}
    return keys.get(int(fifths), "C")

def parse_musicxml(file_bytes, filename, is_chordpro):
    out_title, out_artist, out_bpm, out_time_sig, out_root_key, out_default_beat = "Unknown Song", "Unknown Artist", "120", "4/4", "C", 4
    
    xml_content = None
    if filename.lower().endswith('.mxl'):
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            for name in z.namelist():
                if name.endswith('.xml') and 'container.xml' not in name:
                    xml_content = z.read(name)
                    break
        if not xml_content: raise Exception("XML score not found inside MXL archive.")
    else:
        xml_content = file_bytes

    root = ET.fromstring(xml_content)

    work_title_node = root.find('.//work-title')
    work_title = (work_title_node.text or "") if work_title_node is not None else ""
    if not work_title:
        title_credit = root.find('.//credit[credit-type="title"]/credit-words')
        if title_credit is not None: work_title = (title_credit.text or "")
        if not work_title: 
            first_credit = root.find('.//credit-words')
            if first_credit is not None: work_title = (first_credit.text or "")
    if work_title: out_title = work_title.strip().replace("\n", "").replace("\r", "").replace("'", "''")

    creator_node = root.find('.//creator[@type="composer"]') or root.find('.//creator[@type="lyricist"]')
    creator = (creator_node.text or "") if creator_node is not None else ""
    if not creator:
        credits = [c.text.strip() for c in root.findall('.//credit-words') if c.text and c.text.strip()]
        if len(credits) > 1: creator = credits[1]
    if creator: out_artist = creator.strip().replace("\n", "").replace("\r", "").replace("'", "''")

    attributes = root.find('.//attributes')
    if attributes is not None:
        beats = attributes.find('.//beats')
        beat_type = attributes.find('.//beat-type')
        if beats is not None and beat_type is not None: out_time_sig = f"{beats.text}/{beat_type.text}"
        fifths = attributes.find('.//fifths')
        if fifths is not None: out_root_key = get_major_key_from_fifths(fifths.text)

    sound = root.find('.//sound[@tempo]')
    if sound is not None: out_bpm = sound.get('tempo')

    beats_per_measure = int(out_time_sig.split('/')[0])

    parts = root.findall('.//part')
    if not parts: return out_title, out_artist, out_bpm, out_time_sig, out_root_key, out_default_beat, ""

    chord_part = max(parts, key=lambda p: len(p.findall('.//harmony')), default=parts[0])
    lyric_part = max(parts, key=lambda p: len(p.findall('.//lyric')), default=parts[0])

    c_measures = chord_part.findall('measure')
    l_measures = lyric_part.findall('measure')
    max_measures = max(len(c_measures), len(l_measures))

    # Calcolo del Default Beat
    duration_freq = Counter()
    for i in range(max_measures):
        c_measure = c_measures[i] if i < len(c_measures) else None
        chord_count = 0
        if c_measure is not None:
            for el in c_measure:
                if el.tag == 'harmony': 
                    chord_count += 1
                elif el.tag == 'direction':
                    words = el.find('.//words')
                    if words is not None and words.text:
                        text = words.text.strip()
                        if re.match(r'^(Do|Re|Mi|Fa|Sol|La|Si|C|D|E|F|G|A|B)[#b]?(m|min|maj|dim|aug|sus|M)?\d*(\/(Do|Re|Mi|Fa|Sol|La|Si|C|D|E|F|G|A|B)[#b]?)?$', text, re.IGNORECASE):
                            chord_count += 1
        duration_per_chord = max(1, beats_per_measure // chord_count) if chord_count > 0 else beats_per_measure
        if chord_count > 0: 
            duration_freq[duration_per_chord] += chord_count
    
    if duration_freq: 
        out_default_beat = duration_freq.most_common(1)[0][0]

    # ESTREZIONE LINEARE DEGLI EVENTI
    events = []
    last_added_chord = None
    
    for i in range(max_measures):
        c_measure = c_measures[i] if i < len(c_measures) else None
        l_measure = l_measures[i] if i < len(l_measures) else None
        
        temp_chords = []
        if c_measure is not None:
            for el in c_measure:
                if el.tag == 'harmony':
                    chord_name = get_chord_name(el)
                    if chord_name:
                        temp_chords.append(chord_name)
                elif el.tag == 'direction':
                    words = el.find('.//words')
                    if words is not None and words.text:
                        text = words.text.strip()
                        if re.match(r'^(Do|Re|Mi|Fa|Sol|La|Si|C|D|E|F|G|A|B)[#b]?(m|min|maj|dim|aug|sus|M)?\d*(\/(Do|Re|Mi|Fa|Sol|La|Si|C|D|E|F|G|A|B)[#b]?)?$', text, re.IGNORECASE):
                            chord = format_solfeggio_chord(text)
                            if chord:
                                temp_chords.append(chord[0].upper() + chord[1:])
        
        duration_per_chord = max(1, beats_per_measure // len(temp_chords)) if temp_chords else beats_per_measure
        
        # Mantiene in memoria l'ultimo accordo se la battuta è vuota
        if not temp_chords and last_added_chord:
            events.append({"type": "chord", "text": last_added_chord, "duration": duration_per_chord})
        else:
            for chord in temp_chords:
                events.append({"type": "chord", "text": chord, "duration": duration_per_chord})
                last_added_chord = chord

        if l_measure is not None:
            for el in l_measure.findall('note'):
                lyric_nodes = el.findall('.//lyric')
                for lyric_node in lyric_nodes:
                    text_nd = lyric_node.find('text')
                    if text_nd is not None and text_nd.text and text_nd.text.strip():
                        raw_text = text_nd.text
                        has_hyphen = raw_text.strip().endswith('-') or raw_text.strip().endswith('_')
                        lyric_text = clean_lyric_text(raw_text)
                        
                        syllabic_node = lyric_node.find('syllabic')
                        syllabic = (syllabic_node.text or "") if syllabic_node is not None else ""
                        is_mid_word = syllabic in ["begin", "middle"] or has_hyphen
                        
                        if lyric_text:
                            events.append({"type": "lyric", "text": lyric_text, "is_mid_word": is_mid_word})

    # FORMATTAZIONE TESTUALE LAVA GENIE (Buffer Intelligente)
    final_chart = []
    current_line = ""
    target_line_length = 65
    consecutive_chords = 0
    
    for ev in events:
        if ev["type"] == "chord":
            if is_chordpro:
                chord_str = f"[{ev['text']}:{ev['duration']}]"
            else:
                chord_str = f"[{ev['text']}]"
                if ev['duration'] != out_default_beat:
                    chord_str += f"<beat:{ev['duration']}>"
            
            # Assicura uno spazio prima del nuovo accordo, a meno che non ci sia già
            if current_line and not current_line.endswith(" "):
                current_line += " "
            current_line += chord_str
            consecutive_chords += 1
            
            # Va a capo solo per lunghi intermezzi strumentali (es. intro)
            if consecutive_chords >= 6 and len(current_line) >= target_line_length:
                 final_chart.append(current_line.strip())
                 current_line = ""
                 consecutive_chords = 0
                 
        elif ev["type"] == "lyric":
            consecutive_chords = 0
            
            # "Incolla" l'accordo alla parola rimuovendo spazi superflui
            if current_line and not (current_line.endswith("]") or current_line.endswith(">")):
                if not current_line.endswith(" "):
                    current_line += " "
            
            current_line += ev["text"]
            if not ev["is_mid_word"]:
                current_line += " "
                
            # Va a capo solo a fine parola e se ha superato la lunghezza bersaglio
            if not ev["is_mid_word"] and len(current_line) >= target_line_length:
                final_chart.append(current_line.strip())
                current_line = ""
                
    if current_line.strip():
        final_chart.append(current_line.strip())
        
    return out_title, out_artist, out_bpm, out_time_sig, out_root_key, out_default_beat, "\n".join(final_chart)

# ==========================================
# WEB UI (STREAMLIT)
# ==========================================

st.set_page_config(page_title="Lava Genie Chart Tool", page_icon="🎸", layout="wide")

st.title("🌋 Lava Genie Chart Tool")

st.markdown("""
    <style>
    textarea {
        font-family: 'Courier New', Courier, monospace !important;
    }
    </style>
""", unsafe_allow_html=True)

tab_xml, tab_text = st.tabs(["🎼 MusicXML Converter", "📝 Text-to-Lava (Quick Markup)"])

# --- TAB 1: MUSICXML ---
with tab_xml:
    st.header("Convert MusicXML to Lava+")
    st.markdown("Upload your `.xml` or `.mxl` files from MuseScore, Finale or Sibelius.")
    
    uploaded_files = st.file_uploader("Upload MusicXML", type=["xml", "mxl"], accept_multiple_files=True, key="xml_up")
    
    if uploaded_files:
        col1, col2 = st.columns([1, 2])
        with col1:
            format_choice = st.radio("Export Format:", [
                "Lava Genie format (.txt)", 
                "ChordPro Format (.cho) - For other apps (includes chord duration)"
            ])
            
        is_chordpro = (format_choice != "Lava Genie format (.txt)")

        if len(uploaded_files) == 1:
            file = uploaded_files[0]
            try:
                file_bytes = file.read()
                title, artist, bpm, time_sig, root_key, def_beat, chart = parse_musicxml(file_bytes, file.name, is_chordpro)
                st.success(f"Successfully processed: **{title}**")
                
                c1, c2, c3, c4 = st.columns(4)
                title = c1.text_input("Song Name", title, key="xml_title")
                artist = c2.text_input("Artist", artist, key="xml_artist")
                bpm = c3.text_input("BPM", bpm, key="xml_bpm")
                
                # MODIFICATO: Aggiunto disabled=True per impedire modifiche dannose
                def_beat = c4.text_input("Default Beat", str(def_beat), key="xml_def_beat", disabled=True)

                final_output = ""
                if is_chordpro:
                    final_output = f"{{title: {title}}}\n{{artist: {artist}}}\n{{tempo: {bpm}}}\n{{time: {time_sig}}}\n{{key: {root_key}}}\n\n{chart}"
                    ext = ".cho"
                else:
                    final_output = f"---\nname: '{title}'\nartist: '{artist}'\nbpm: {bpm}\ntimeSignature: '{time_sig}'\nrootKey: '{root_key}'\nbeat: {def_beat}\n---\n{chart}"
                    ext = "_LavaGenie.txt"

                st.text_area("Conversion Result:", final_output, height=400)
                safe_title = re.sub(r'[\\/*?:"<>|]', "", title)
                st.download_button(label="Download File", data=final_output, file_name=f"{safe_title}{ext}", mime="text/plain")
                
            except Exception as e:
                st.error(f"Error processing {file.name}: {e}")

        else:
            st.info(f"Batch Mode: {len(uploaded_files)} files ready for conversion.")
            if st.button("Start Bulk Conversion"):
                zip_buffer = io.BytesIO()
                success_count = 0
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                    for file in uploaded_files:
                        try:
                            file_bytes = file.read()
                            title, artist, bpm, time_sig, root_key, def_beat, chart = parse_musicxml(file_bytes, file.name, is_chordpro)
                            if is_chordpro:
                                final_output = f"{{title: {title}}}\n{{artist: {artist}}}\n{{tempo: {bpm}}}\n{{time: {time_sig}}}\n{{key: {root_key}}}\n\n{chart}"
                                ext = ".cho"
                            else:
                                final_output = f"---\nname: '{title}'\nartist: '{artist}'\nbpm: {bpm}\ntimeSignature: '{time_sig}'\nrootKey: '{root_key}'\nbeat: {def_beat}\n---\n{chart}"
                                ext = "_LavaGenie.txt"
                            safe_title = re.sub(r'[\\/*?:"<>|]', "", title) or "Unknown"
                            zf.writestr(f"{safe_title}{ext}", final_output)
                            success_count += 1
                        except Exception as e:
                            st.error(f"Error on {file.name}: {e}")
                
                st.success(f"Done! {success_count} files processed.")
                st.download_button(label="Download ZIP Archive", data=zip_buffer.getvalue(), file_name="Batch_Export.zip", mime="application/zip")

# --- TAB 2: TEXT MARKUP ---
with tab_text:
    st.header("Quick Text-to-Lava Converter")
    
    with st.expander("❓ Help & Instructions: How to prepare your text file"):
        st.markdown("""
        **Welcome to the Quick Text-to-Lava Converter!** This tool lets you take standard chord sheets from the web and convert them into perfectly timed Lava Genie charts, saving you time compared to manual editing inside the app.

        ### 🎹 1. Spacing and Alignment
        The engine uses "spatial math" to place the chords exactly where they belong.
        * Write your chords using a **monospaced font** (like Notepad, Courier, or Consolas).
        * Use the **spacebar** (never the TAB key) to position the chord *exactly* above the word or syllable where the change happens.

        ### ⏱️ 2. Setting Chord Durations (The Punctuation Rule)
        By default, every chord lasts for your **Default Beat** (which can be set to 1, 2, 3, 4, or 6 beats). To change a specific chord's duration, simply attach a basic punctuation mark directly to the chord name (no spaces):
        * **Chord** (No symbol) = Default Beat (No editing needed!)
        * **Chord!** (Exclamation) = 6 beats *(Perfect for 6/8 time signatures!)*
        * **Chord:** (Colon) = 4 beats
        * **Chord;** (Semicolon) = 3 beats
        * **Chord,** (Comma) = 2 beats
        * **Chord.** (Period) = 1 beat
        
        > 💡 **PRO TIP FOR ALIGNMENT:** When you add a punctuation mark to a chord, remember to **delete one empty space** immediately after it. This prevents the rest of the chords on that line from shifting one character to the right and losing their perfect alignment with the lyrics!
        
        *Example:*
        ```text
        C                 G,         F.   C.
        This is just a sample lyric line
        ```

        ### 🎸 3. Instrumental Breaks
        If you write a line of chords with no lyrics underneath (like an intro: `Bm, A, Em`), the tool will automatically format it as an instrumental break. Just make sure to keep chords on one line and lyrics on the next!

        ### 📁 4. ChordPro Import (.cho)
        You can upload standard ChordPro files using the upload button. If your chords are already written inline (e.g., `[C]Hello [G]world`), the tool will recognize them. You can even apply the punctuation rules inside the brackets to fix the timing (e.g., `[C]Hello [G,]world`).
        
        ### 📝 5. Song Metadata (Important!)
        Before clicking the **"Convert Text to Lava"** button, remember to fill in the fields like **Song Name**, **Artist**, **BPM**, **Time Signature**, and **Key**. The tool will combine everything into the required header block for Lava Genie.
        """)

    uploaded_text_file = st.file_uploader("Import a text or ChordPro file (.txt, .cho, .chordpro)", type=["txt", "cho", "chordpro"], key="text_file_import")
    
    default_name = "My Song"
    default_artist = "Unknown"
    default_bpm = "120"
    default_time_sig = "4/4"
    default_key = "C"
    default_text = ""
    
    if uploaded_text_file is not None:
        try:
            default_text = uploaded_text_file.read().decode("utf-8")
            filename_clean = uploaded_text_file.name.rsplit('.', 1)[0]
            if " - " in filename_clean:
                parts_name = filename_clean.split(" - ", 1)
                default_artist = parts_name[0].strip()
                default_name = parts_name[1].strip()
            else:
                default_name = filename_clean.strip()
                
            title_match = re.search(r'{title:\s*(.*?)}', default_text, re.IGNORECASE) or re.search(r'{t:\s*(.*?)}', default_text, re.IGNORECASE)
            artist_match = re.search(r'{artist:\s*(.*?)}', default_text, re.IGNORECASE) or re.search(r'{a:\s*(.*?)}', default_text, re.IGNORECASE)
            tempo_match = re.search(r'{tempo:\s*(.*?)}', default_text, re.IGNORECASE) or re.search(r'{bpm:\s*(.*?)}', default_text, re.IGNORECASE)
            key_match = re.search(r'{key:\s*(.*?)}', default_text, re.IGNORECASE) or re.search(r'{k:\s*(.*?)}', default_text, re.IGNORECASE)
            time_match = re.search(r'{time:\s*(.*?)}', default_text, re.IGNORECASE)
            
            if title_match: default_name = title_match.group(1).strip()
            if artist_match: default_artist = artist_match.group(1).strip()
            if tempo_match: default_bpm = tempo_match.group(1).strip()
            if key_match: default_key = key_match.group(1).strip()
            if time_match: default_time_sig = time_match.group(1).strip()
            
        except Exception as e:
            st.error(f"Error reading text file: {e}")

    row1_col1, row1_col2, row1_col3 = st.columns(3)
    t_name = row1_col1.text_input("Song Name", default_name, key="txt_title")
    t_artist = row1_col2.text_input("Artist", default_artist, key="txt_artist")
    t_bpm = row1_col3.text_input("BPM", default_bpm, key="txt_bpm")

    row2_col1, row2_col2, row2_col3 = st.columns(3)
    t_time_sig = row2_col1.text_input("Time Signature", default_time_sig, key="txt_time_sig")
    t_key = row2_col2.text_input("Key", default_key, key="txt_key")
    t_def_beat = row2_col3.selectbox("Default Beat", options=[1, 2, 3, 4, 6], index=3, key="txt_def_beat")

    input_text = st.text_area("Chords & Lyrics Content (Paste or edit imported file):", value=default_text, height=300, placeholder="C           G,\nMy sample lyrics...")

    if st.button("Convert Text to Lava"):
        if input_text.strip():
            try:
                converted_chart = convert_text_markup_to_lava(input_text, t_def_beat)
                final_header = f"---\nname: '{t_name}'\nartist: '{t_artist}'\nbpm: {t_bpm}\ntimeSignature: '{t_time_sig}'\nrootKey: '{t_key}'\nbeat: {t_def_beat}\n---\n"
                full_output = final_header + converted_chart
                
                st.subheader("Result (Copy & Paste into Genie Song Editor):")
                st.text_area("Final Output:", full_output, height=300)
                
                st.download_button(
                    label="Download converted .txt File",
                    data=full_output,
                    file_name=f"{t_name.replace(' ', '_')}_Lava.txt",
                    mime="text/plain"
                )
            except Exception as e:
                st.error(f"An error occurred: {e}")
        else:
            st.warning("Please paste or import some text first.")
