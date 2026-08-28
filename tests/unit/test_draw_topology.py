from app.ingestion.calendar_draws.topology import parse_direct_draw_text


def test_review_only_parser_stages_singles_round_one_candidates_from_direct_bwf_table_text() -> None:
    text = """
MS
       Member ID   St.   Cnty Flag             Round 1      Round 2
   1    73442            INA         J. Christie [1]
   2    84838            MAS         Leong Jun Hao
   3    97174            JPN         Koki Watanabe
   4    65634            HKG         Jason Gunawan
"""

    nodes = parse_direct_draw_text(text, discipline="MS")

    assert [(node.participant_1_label, node.participant_2_label) for node in nodes] == [
        ("J. Christie [1]", "Leong Jun Hao"),
        ("Koki Watanabe", "Jason Gunawan"),
    ]
    assert all(node.round_label == "Round 1 (source table)" for node in nodes)


def test_review_only_parser_stages_doubles_teams_from_explicit_two_member_source_rows() -> None:
    text = """
MD
       Member ID   St.   Cnty Flag             Round 1      Round 2
        61444            KOR         Kim Won Ho [1]
   1    66513            KOR         Seo Seung Jae
        68633            INA         Leo Rolly Carnando
   2    84786            INA         Daniel Marthin
"""

    nodes = parse_direct_draw_text(text, discipline="MD")

    assert len(nodes) == 1
    assert nodes[0].participant_1_label == "Kim Won Ho [1] / Seo Seung Jae"
    assert nodes[0].participant_2_label == "Leo Rolly Carnando / Daniel Marthin"


def test_review_only_parser_refuses_ambiguous_numbered_table_positions() -> None:
    assert parse_direct_draw_text("3 73442 INA J. Christie", discipline="MS") == []


def test_review_only_parser_does_not_treat_a_printed_date_range_as_a_matchup() -> None:
    text = """
Date                           City, Country              Website
01 - 06 Sep 2026               Shenzhen, CHN
   1    73442            INA         J. Christie [1]
   2    84838            MAS         Leong Jun Hao
"""

    nodes = parse_direct_draw_text(text, discipline="MS")

    assert len(nodes) == 1
    assert nodes[0].participant_1_label == "J. Christie [1]"


def test_review_only_parser_handles_the_actual_pypdf_singles_extraction_order() -> None:
    text = """
Date
01 - 06 Sep 2026
Member IDSt. CntyFlag Round 1
1 73442 INA
  J. Christie [1]
2 84838 MAS
  Leong Jun Hao
3 97174 JPN
  Koki Watanabe
4 65634 HKG
  Jason Gunawan
Round 2
Semifinals
"""

    nodes = parse_direct_draw_text(text, discipline="MS")

    assert [(node.participant_1_label, node.participant_2_label) for node in nodes] == [
        ("J. Christie [1]", "Leong Jun Hao"),
        ("Koki Watanabe", "Jason Gunawan"),
    ]


def test_review_only_parser_handles_the_actual_pypdf_doubles_extraction_order() -> None:
    text = """
Member IDSt. CntyFlag Round 1
1 66513
61444
KOR
KOR
 Kim Won Ho [1]
 Seo Seung Jae
2 84786
68633
INA
INA
 Leo Rolly Carnando
 Daniel Marthin
"""

    nodes = parse_direct_draw_text(text, discipline="MD")

    assert len(nodes) == 1
    assert nodes[0].participant_1_label == "Kim Won Ho [1] / Seo Seung Jae"


def test_review_only_parser_retains_explicit_source_byes_as_non_played_candidates() -> None:
    text = """
Member IDSt. CntyFlag Round 1
1 59880
81599
CHN
CHN
 Liu Sheng Shu [1]
 Tan Ning
2
Bye 1
3 18889
62277
CHN
CHN
 Bao Li Jing
 Cao Zi Han
4 71883
23008
MAS
MAS
 Low Zi Yu
 Noraqilah Maisarah
Round 2
"""

    nodes = parse_direct_draw_text(text, discipline="WD")

    assert [(node.participant_1_label, node.participant_2_label) for node in nodes] == [
        ("Liu Sheng Shu [1] / Tan Ning", "BYE"),
        ("Bao Li Jing / Cao Zi Han", "Low Zi Yu / Noraqilah Maisarah"),
    ]
