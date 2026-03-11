from gyn_kol.resolution.normalise import normalise_name


def test_strip_titles():
    assert normalise_name("Dr Jane Smith") == "jane smith"
    assert normalise_name("Prof. Robert Jones") == "robert jones"
    assert normalise_name("A/Prof Sarah Brown") == "sarah brown"
    assert normalise_name("Associate Professor David Lee") == "david lee"


def test_strip_qualifications():
    assert normalise_name("Jane Smith MBBS FRANZCOG") == "jane smith"
    assert normalise_name("Robert Jones MD PhD") == "robert jones"


def test_handle_punctuation():
    assert normalise_name("O'Brien, Catherine") == "o'brien catherine"
    assert normalise_name("Smith-Jones, M.") == "smith-jones m"


def test_handle_initials():
    assert normalise_name("J. A. Smith") == "j a smith"
    assert normalise_name("Smith, J A") == "smith j a"


def test_hyphenated_surnames():
    assert normalise_name("Dr. Anna-Maria Gonzalez-Smith") == "anna-maria gonzalez-smith"


def test_empty_and_whitespace():
    assert normalise_name("") == ""
    assert normalise_name("   ") == ""
