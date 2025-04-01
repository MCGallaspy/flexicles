import streamlit as st
import xml.etree.ElementTree as ET
import sqlite3
import pandas as pd

from io import StringIO


schema_script ="""
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS lexemes(
    rowid INTEGER PRIMARY KEY,
    lemma TEXT,
    morpheme_type TEXT
);

CREATE TABLE IF NOT EXISTS spellings(
    rowid INTEGER PRIMARY KEY,
    form TEXT,
    lexeme INTEGER,
    FOREIGN KEY(lexeme) REFERENCES lexemes(rowid)
);

CREATE TABLE IF NOT EXISTS senses(
    rowid INTEGER PRIMARY KEY,
    gloss TEXT,
    lexeme INTEGER,
    part_of_speech TEXT,
    FOREIGN KEY(lexeme) REFERENCES lexemes(rowid)
);

CREATE TABLE IF NOT EXISTS sense_grammatical_info(
    name TEXT,
    value TEXT,
    sense INTEGER,
    FOREIGN KEY(sense) REFERENCES senses(rowid)
);

CREATE TABLE IF NOT EXISTS texts(
    rowid INTEGER PRIMARY KEY,
    text_name TEXT NOT NULL,
    narrative_order INTEGER NOT NULL,
    word TEXT,
    UNIQUE(text_name, narrative_order)
);

CREATE TABLE IF NOT EXISTS text_morphemes(
    spellingid INTEGER,
    textid INTEGER,
    morpheme_order INTEGER NOT NULL,
    FOREIGN KEY(spellingid) REFERENCES spellings(rowid),
    FOREIGN KEY(textid) REFERENCES texts(rowid),
    PRIMARY KEY(spellingid, textid, morpheme_order)
);
"""

st.title("FLEx to tables")

about = st.expander("About")
about.markdown(f"""
# What is this?

This tool converts FLEx lexicons exported into the LIFT format into a set of tables in a relational database. Additionally, it accepts interlinear texts exported as XML from FLEx, and will link the text words to lexicon entries.

# How does it work?

Any XML document is able to be represented as a set of relational tables. By referencing the LIFT standard, I was able to create such a set of tables. Note that with tabular representation I am using is not completely able to replace LIFT. Some things that are modeled by LIFT are not supported by me, such as (but not limited to) multiple vernacular spelling systems.

# Will it work with my data?

Try it and see. This is a work in progress. If there is an issue, send me an email explaining the problem along with your XML data, and I'll try to address it: gallaspy.michael@gmail.com

Please note that I can't commit to any particular timeline for fixing issues.

# How can I contribute?

If you like to code, then pull requests are welcome. :)

# What is the schema for the tabular representation?

The tables are defined in sqlite-flavored SQL:

```sql
{schema_script}
```
""")

with st.form("Upload XML Files"):
    st.header("Upload XML Files")
    lexicon_file = st.file_uploader("LIFT Lexicon")
    texts_file = st.file_uploader("Interlinear texts XML (`.flextext`)")
    st.form_submit_button("Upload")

if lexicon_file:
    DATABASE_NAME = ":memory:"
    con = sqlite3.connect(DATABASE_NAME)
    st.session_state['dbcon'] = con
    cur = con.cursor()
    cur.executescript(schema_script)
    
    tree = ET.parse(lexicon_file)
    root = tree.getroot()
    for entry in root.findall('entry'):
        lexeme_form = entry.find('./lexical-unit/form')
        lemma = lexeme_form.find('text').text
        morpheme_type = entry.find('./trait[@name="morph-type"]').attrib['value']
        
        cur.execute(f"INSERT INTO lexemes VALUES (NULL, '{lemma}', '{morpheme_type}')")
        con.commit()
        
        lexeme_id = cur.lastrowid
        cur.execute(f"INSERT INTO spellings VALUES (NULL, '{lemma}', {lexeme_id})")
        for variant_form in entry.findall('./variant/form/text'):
            cur.execute(f"INSERT INTO spellings VALUES (NULL, '{variant_form.text}', {lexeme_id})")
        con.commit()

        for sense in entry.findall('sense'):
            gloss = sense.find('./gloss/text').text
            part_of_speech = sense.find('grammatical-info').attrib['value']
            cur.execute(f"INSERT INTO senses VALUES (NULL, '{gloss}', {lexeme_id}, '{part_of_speech}')")
            con.commit()
            sense_id = cur.lastrowid
            for trait in sense.findall('./grammatical-info/trait'):
                name = trait.attrib['name']
                value = trait.attrib['value']
                cur.execute(f"INSERT INTO sense_grammatical_info VALUES ('{name}', '{value}', {lexeme_id})")
            con.commit()
    
    if texts_file:
        tree = ET.parse(texts_file)
        root = tree.getroot()
        for text in root.findall('interlinear-text'):
            title = root.find(".//item[@type='title']").text
            
            word_values = []
            for narrative_order, word in enumerate(text.findall('.//word')):
                word_values.append([title, narrative_order, word.find('./item').text])
            cur.executemany(f"INSERT INTO texts VALUES (NULL, ?, ?, ?)", word_values)
            con.commit()

            morpheme_values = []
            for narrative_order, word in enumerate(text.findall('.//word')):
                query = f"SELECT rowid FROM texts WHERE text_name='{title}' AND narrative_order={narrative_order}"
                textid = cur.execute(query).fetchone()[0]
                for morpheme_order, morph in enumerate(word.findall('.//morph')):
                    gloss = morph.find("./item[@type='gls']")
                    spelling = morph.find("./item[@type='txt']")
                    if (gloss is None) or (spelling is None):
                        continue
                    gloss = gloss.text
                    spelling = spelling.text
                    query = f"""SELECT spellings.rowid AS spellingid
                                FROM spellings, senses
                                WHERE spellings.lexeme=senses.lexeme
                                  AND senses.gloss='{gloss}' AND spellings.form='{spelling}'"""
                    spellingid = cur.execute(query).fetchone()[0]
                    morpheme_values.append([spellingid, textid, morpheme_order])
            cur.executemany(f"INSERT INTO text_morphemes VALUES (?, ?, ?)", morpheme_values)
            con.commit()
    
    default_query = """
SELECT spellings.form, senses.gloss, senses.part_of_speech, lexemes.morpheme_type
FROM spellings, senses, lexemes
WHERE spellings.lexeme=senses.lexeme AND senses.lexeme=lexemes.rowid
LIMIT 100
""".strip()
    query = st.text_area("Custom query", value=default_query).strip()
    if query:
        try:
            cur = con.cursor()
            cur.execute(query)
            st.write("Query result")
            st.dataframe(pd.DataFrame(cur.fetchall()))
        except Exception as e:
            st.error(f"Bad query\n{str(e)}")
    
    lexemes_df = pd.read_sql_query("SELECT * FROM lexemes", con)
    spellings_df = pd.read_sql_query("SELECT * FROM spellings", con)
    senses_df = pd.read_sql_query("SELECT * FROM senses", con)
    gramm_df = pd.read_sql_query("SELECT * FROM sense_grammatical_info", con)
    texts_df = pd.read_sql_query("SELECT * FROM texts", con)
    morphs_df = pd.read_sql_query("SELECT * FROM text_morphemes", con)

    st.write("Lexemes")
    st.dataframe(lexemes_df, hide_index=True)
    st.write("Spellings")
    st.dataframe(spellings_df, hide_index=True)
    st.write("Senses")
    st.dataframe(senses_df, hide_index=True)
    st.write("Grammatical Info")
    st.dataframe(gramm_df, hide_index=True)
    st.write("Texts")
    st.dataframe(texts_df, hide_index=True)
    st.write("Text Morphemes")
    st.dataframe(morphs_df, hide_index=True)