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
            
        words = line.split()
        is_chord_line = len(words) > 0 and all(re.match(r'^[A-G][a-zA-Z0-9#b/]*[:;,\.]?$', w) for w in words)
                
        if is_chord_line:
            chord_matches = [(m.group(), m.start()) for m in re.finditer(r'\S+', line)]
            
            lyric_line = ""
            if i + 1 < len(lines):
                next_line = lines[i+1].rstrip('\r\n')
                words_next = next_line.split()
                is_next_chord = len(words_next) > 0 and all(re.match(r'^[A-G][a-zA-Z0-9#b/]*[:;,\.]?$', w) for w in words_next)
                if next_line.strip() and not is_next_chord:
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
        
    return "\n".join(output_lines)

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
    kind_text_attr = kind_node.get('text') if kind_node is not None else ""
    
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
        bass_step = bass.find('bass-step').text if bass.find('bass-step') is not None else ""
        bass_alter = bass.find('bass-alter').text if bass.find('bass-alter') is not None else None
        bass_accidental = "b" if bass_alter == "-1" else ("#" if bass_alter == "1" else "")
        if bass_step: bass_note = f"/{bass_step}{bass_accidental}"

    return f"{root_note}{suffix}{bass_note}"

def get_major_key_from_
