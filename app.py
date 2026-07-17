import streamlit as st
import zipfile
import xml.etree.ElementTree as ET
import re
from collections import Counter
import io

# ==========================================
# MOTORE MUSICXML (XML -> Testo)
# ==========================================

def clean_lyric_text(text):
    if not text: return ""
    cleaned = text.strip()
    cleaned = cleaned.replace("’", "'").replace("‘", "'").replace("`", "'")
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
    if kind_text_attr and kind_text_attr.lower() in ["add9", "sus9"]: suffix = kind_text_attr
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

    # ESTRAZIONE ORDINATA DEGLI EVENTI
    events = []
    last_added_chord = None
    
    for i in range(max_measures):
        c_measure = c_measures[i] if i < len(c_measures) else None
        l_measure = l_measures[i] if i < len(l_measures) else None
        
        temp_chords_count = 0
        if c_measure is not None:
            for el in c_measure:
                if el.tag == 'harmony': 
                    temp_chords_count += 1
                elif el.tag == 'direction':
                    words = el.find('.//words')
                    if words is not None and words.text and re.match(r'^(Do|Re|Mi|Fa|Sol|La|Si|C|D|E|F|G|A|B)[#b]?(m|min|maj|dim|aug|sus|M)?\d*(\/(Do|Re|Mi|Fa|Sol|La|Si|C|D|E|F|G|A|B)[#b]?)?$', words.text.strip(), re.IGNORECASE):
                        temp_chords_count += 1
                        
        duration_per_chord = max(1, beats_per_measure // temp_chords_count) if temp_chords_count > 0 else beats_per_measure

        if chord_part == lyric_part and c_measure is not None:
            if temp_chords_count == 0 and last_added_chord:
                events.append({"type": "chord", "text": last_added_chord, "duration": duration_per_chord})
            
            for el in c_measure:
                if el.tag == 'harmony':
                    chord_name = get_chord_name(el)
                    if chord_name:
                        events.append({"type": "chord", "text": chord_name, "duration": duration_per_chord})
                        last_added_chord = chord_name
                        
                elif el.tag == 'direction':
                    words = el.find('.//words')
                    if words is not None and words.text:
                        text = words.text.strip()
                        if re.match(r'^(Do|Re|Mi|Fa|Sol|La|Si|C|D|E|F|G|A|B)[#b]?(m|min|maj|dim|aug|sus|M)?\d*(\/(Do|Re|Mi|Fa|Sol|La|Si|C|D|E|F|G|A|B)[#b]?)?$', text, re.IGNORECASE):
                            chord = format_solfeggio_chord(text)
                            if chord:
                                c_name = chord[0].upper() + chord[1:]
                                events.append({"type": "chord", "text": c_name, "duration": duration_per_chord})
                                last_added_chord = c_name
                                
                elif el.tag == 'note':
                    lyric_nodes = el.findall('.//lyric')
                    target_lyric = None
                    for n in lyric_nodes:
                        if n.get('number') == '1':
                            target_lyric = n
                            break
                    if not target_lyric and lyric_nodes:
                        target_lyric = lyric_nodes[0]
                        
                    if target_lyric is not None:
                        text_nd = target_lyric.find('text')
                        if text_nd is not None and text_nd.text and text_nd.text.strip():
                            raw_text = text_nd.text
                            has_hyphen = raw_text.strip().endswith('-') or raw_text.strip().endswith('_')
                            lyric_text = clean_lyric_text(raw_text)
                            
                            syllabic_node = target_lyric.find('syllabic')
                            syllabic = (syllabic_node.text or "") if syllabic_node is not None else ""
                            is_mid_word = syllabic in ["begin", "middle"] or has_hyphen
                            
                            if lyric_text:
                                events.append({"type": "lyric", "text": lyric_text, "is_mid_word": is_mid_word})
        else:
            if temp_chords_count == 0 and last_added_chord:
                events.append({"type": "chord", "text": last_added_chord, "duration": duration_per_chord})
                
            if c_measure is not None:
                for el in c_measure:
                    if el.tag == 'harmony':
                        chord_name = get_chord_name(el)
                        if chord_name:
                            events.append({"type": "chord", "text": chord_name, "duration": duration_per_chord})
                            last_added_chord = chord_name
                    elif el.tag == 'direction':
                        words = el.find('.//words')
                        if words is not None and words.text:
                            text = words.text.strip()
                            if re.match(r'^(Do|Re|Mi|Fa|Sol|La|Si|C|D|E|F|G|A|B)[#b]?(m|min|maj|dim|aug|sus|M)?\d*(\/(Do|Re|Mi|Fa|Sol|La|Si|C|D|E|F|G|A|B)[#b]?)?$', text, re.IGNORECASE):
                                chord = format_solfeggio_chord(text)
                                if chord:
                                    c_name = chord[0].upper() + chord[1:]
                                    events.append({"type": "chord", "text": c_name, "duration": duration_per_chord})
                                    last_added_chord = c_name
            
            if l_measure is not None:
                for el in l_measure.findall('note'):
                    lyric_nodes = el.findall('.//lyric')
                    target_lyric = None
                    for n in lyric_nodes:
                        if n.get('number') == '1':
                            target_lyric = n
                            break
                    if not target_lyric and lyric_nodes:
                        target_lyric = lyric_nodes[0]
                        
                    if target_lyric is not None:
                        text_nd = target_lyric.find('text')
                        if text_nd is not None and text_nd.text and text_nd.text.strip():
                            raw_text = text_nd.text
                            has_hyphen = raw_text.strip().endswith('-') or raw_text.strip().endswith('_')
                            lyric_text = clean_lyric_text(raw_text)
                            
                            syllabic_node = target_lyric.find('syllabic')
                            syllabic = (syllabic_node.text or "") if syllabic_node is not None else ""
                            is_mid_word = syllabic in ["begin", "middle"] or has_hyphen
                            
                            if lyric_text:
                                events.append({"type": "lyric", "text": lyric_text, "is_mid_word": is_mid_word})

    # FORMATTAZIONE TESTUALE
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
            
            if current_line and not current_line.endswith(" "):
                current_line += " "
            current_line += chord_str
            consecutive_chords += 1
            
            if consecutive_chords >= 6 and len(current_line) >= target_line_length:
                 final_chart.append(current_line.strip())
                 current_line = ""
                 consecutive_chords = 0
                 
        elif ev["type"] == "lyric":
            consecutive_chords = 0
            
            if current_line and not (current_line.endswith("]") or current_line.endswith(">")):
                if not current_line.endswith(" "):
                    current_line += " "
            
            current_line += ev["text"]
            if not ev["is_mid_word"]:
                current_line += " "
                
            if not ev["is_mid_word"] and len(current_line) >= target_line_length:
                final_chart.append(current_line.strip())
                current_line = ""
                
    if current_line.strip():
        final_chart.append(current_line.strip())
        
    return out_title, out_artist, out_bpm, out_time_sig, out_root_key, out_default_beat, "\n".join(final_chart)

# ==========================================
# PARSER TEXT-TO-LAVA (Testo -> Testo)
# ==========================================

def is_chord_line(line):
    cleaned = line.strip()
    if not cleaned: return False
    tokens = cleaned.split()
    chord_pattern = re.compile(r'^\[?(Do|Re|Mi|Fa|Sol|La|Si|C|D|E|F|G|A|B)[#b]?(m|min|maj|dim|aug|sus|M)?\d*(\/(Do|Re|Mi|Fa|Sol|La|Si|C|D|E|F|G|A|B)[#b]?)?\]?$', re.IGNORECASE)
    match_count = sum(1 for t in tokens if chord_pattern.match(t))
    return match_count > 0 and (match_count / len(tokens)) > 0.5

def format_chord(chord_text):
    c = chord_text.replace('[', '').replace(']', '').strip()
    return f"[{c}]"

def text_to_lava(text):
    lines = text.split('\n')
    output = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line:
            i += 1
            continue
        
        if is_chord_line(line):
            chords = []
            for match in re.finditer(r'\S+', line):
                chords.append((match.group(), match.start()))
            
            if i + 1 < len(lines) and not is_chord_line(lines[i+1]) and lines[i+1].strip():
                lyrics_line = lines[i+1].rstrip()
                merged_line = ""
                last_idx = 0
                
                for chord, pos in chords:
                    if pos > len(lyrics_line):
                        merged_line += lyrics_line[last_idx:] + " " * (pos - len(lyrics_line)) + format_chord(chord)
                        last_idx = len(lyrics_line)
                    else:
                        merged_line += lyrics_line[last_idx:pos] + format_chord(chord)
                        last_idx = pos
                
                merged_line += lyrics_line[last_idx:]
                output.append(merged_line)
                i += 2 
            else:
                chord_only_line = " ".join([format_chord(c) for c, _ in chords])
                output.append(chord_only_line)
                i += 1
        else:
            output.append(line)
            i += 1
            
    return "\n".join(output)

# ==========================================
# PARSER LAVA-TO-CHORDPRO (Testo -> Testo)
# ==========================================

def lava_to_chordpro(lava_text):
    lines = lava_text.split('\n')
    output_lines = []
    default_beat = 4 # Fallback
    
    # 1. Estrai l'intestazione YAML per trovare il beat di default e tradurre in ChordPro
    in_header = False
    body_lines = []
    chordpro_directives = []
    
    for line in lines:
        if line.strip() == "---":
            if not in_header and not body_lines:
                in_header = True
            elif in_header:
                in_header = False
            else:
                body_lines.append(line)
        elif in_header:
            # Dividi la chiave dal valore (es. "name: 'Canzone'")
            parts = line.split(":", 1)
            if len(parts) == 2:
                key = parts[0].strip()
                # Rimuovi spazi e apici (sia singoli che doppi) dal valore
                val = parts[1].strip().strip("'").strip('"')
                
                # Mappatura Lava Genie -> ChordPro standard
                if key == "name":
                    chordpro_directives.append(f"{{title: {val}}}")
                elif key == "artist":
                    chordpro_directives.append(f"{{artist: {val}}}")
                elif key == "bpm":
                    chordpro_directives.append(f"{{tempo: {val}}}")
                elif key == "timeSignature":
                    chordpro_directives.append(f"{{time: {val}}}")
                elif key == "rootKey":
                    chordpro_directives.append(f"{{key: {val}}}")
                elif key == "beat":
                    try:
                        default_beat = int(val)
                    except ValueError:
                        pass
                    # Il beat viene salvato per la logica ma intenzionalmente NON scritto in output
        else:
            body_lines.append(line)
            
    # Stampa le direttive all'inizio del file
    if chordpro_directives:
        output_lines.extend(chordpro_directives)
        output_lines.append("") # Riga vuota di separazione tra header e corpo
        
    # 2. Elabora il corpo del testo
    # Regex per trovare: [Accordo] oppure [Accordo]<beat:X>
    pattern = re.compile(r'\[(.*?)\](?:<beat:(\d+)>)?')
    
    for line in body_lines:
        if not line.strip():
            output_lines.append(line)
            continue
            
        new_line = line
        # Rimpiazza ogni occorrenza usando la funzione replacer
        def replacer(match):
            chord = match.group(1)
            beat = int(match.group(2)) if match.group(2) else default_beat
            return f"[{chord}:{beat}]"
            
        new_line = pattern.sub(replacer, new_line)
        output_lines.append(new_line)
        
    return "\n".join(output_lines)

# ==========================================
# WEB UI (STREAMLIT)
# ==========================================

st.set_page_config(page_title="Lava Genie Tools", page_icon="🎸", layout="wide")

st.title("🎸 Lava Genie Conversion Tools")

tab1, tab2, tab3 = st.tabs(["XML to Lava Genie", "Quick Markup (Text to Lava)", "Lava to ChordPro"])

# --- TAB 1: XML to Lava ---
with tab1:
    st.markdown("Upload a **MusicXML** file to generate a perfectly formatted chart for Lava Genie.")
    
    c1, c2 = st.columns([2, 1])
    with c1:
        uploaded_file = st.file_uploader("Upload MusicXML (.xml, .mxl)", type=["xml", "mxl"], key="xml_up")
    with c2:
        st.write("")
        st.write("")
        is_chordpro = st.toggle("Generate standard ChordPro format ([C:4])", value=False)

    if uploaded_file:
        try:
            file_bytes = uploaded_file.read()
            title, artist, bpm, time_sig, root_key, def_beat, chart = parse_musicxml(file_bytes, uploaded_file.name, is_chordpro)
            
            st.success("XML parsed successfully!")
            
            col1, col2 = st.columns(2)
            ui_title = col1.text_input("Song Name", title)
            ui_artist = col2.text_input("Artist", artist)
            
            col3, col4, col5, col6 = st.columns(4)
            ui_bpm = col3.text_input("BPM", bpm)
            ui_time = col4.text_input("Time Signature", time_sig)
            ui_key = col5.text_input("Root Key", root_key)
            ui_beat = col6.text_input("Default Beat", str(def_beat))
            
            final_output = f"---\nname: '{ui_title}'\nartist: '{ui_artist}'\nbpm: {ui_bpm}\ntimeSignature: '{ui_time}'\nrootKey: '{ui_key}'\nbeat: {ui_beat}\n---\n{chart}"
            
            st.text_area("Final Output", value=final_output, height=400)
            
            safe_title = re.sub(r'[\\/*?:"<>|]', "", ui_title).replace(" ", "_")
            st.download_button(
                label="📥 Download TXT",
                data=final_output,
                file_name=f"{safe_title}_LavaGenie.txt",
                mime="text/plain"
            )
        except Exception as e:
            st.error(f"An error occurred: {e}")

# --- TAB 2: Text to Lava ---
with tab2:
    st.markdown("Paste your standard plain-text lyrics with chords above them. The tool will merge them into Lava Genie format.")
    
    raw_text = st.text_area("Paste Lyrics & Chords here:", height=250, placeholder="[C]           [G]\nHello darkness my old friend")
    
    if st.button("Convert to Lava Genie Format", type="primary"):
        if raw_text.strip():
            result = text_to_lava(raw_text)
            st.success("Conversion successful!")
            st.text_area("Result:", value=result, height=250)
            st.download_button("📥 Download", result, file_name="converted_chart.txt")
        else:
            st.warning("Please paste some text first.")

# --- TAB 3: Lava to ChordPro ---
with tab3:
    st.markdown("Paste a **Lava Genie** format text (`[C]<beat:2> text`). The tool will read the header and convert it to **Standard ChordPro** (`[C:2] text`).")
    
    lava_text = st.text_area("Paste Lava Genie Text here:", height=250, placeholder="---\nname: 'My Song'\nbeat: 4\n---\n[C]<beat:2>Hello [G]world")
    
    if st.button("Convert to ChordPro", type="primary"):
        if lava_text.strip():
            cp_result = lava_to_chordpro(lava_text)
            st.success("Conversion successful!")
            st.text_area("ChordPro Result:", value=cp_result, height=250)
            
            # --- LOGICA PER IL NOME DEL FILE DINAMICO ---
            # Cerca il titolo dentro le direttive ChordPro generate
            title_match = re.search(r'\{title:\s*(.*?)\}', cp_result, re.IGNORECASE)
            
            if title_match and title_match.group(1).strip():
                # Pulisce il titolo da caratteri illegali per i nomi dei file e sostituisce gli spazi con underscore
                raw_title = title_match.group(1).strip()
                safe_title = re.sub(r'[\\/*?:"<>|]', "", raw_title).replace(" ", "_")
            else:
                safe_title = "Unknown_Song"
                
            download_filename = f"{safe_title}_chordpro.txt"
            
            st.download_button(
                label="📥 Download ChordPro", 
                data=cp_result, 
                file_name=download_filename,
                mime="text/plain"
            )
        else:
            st.warning("Please paste some Lava Genie text first.")
