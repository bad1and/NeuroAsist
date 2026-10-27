from scripts import check_docs


def test_cyrillic_and_duplicate_heading_anchors():
    text = "# Голос и память\n## 05 · Голос и аватар\n## Голос и память\n## API `v3`\n"
    assert check_docs.markdown_anchors(text) == {
        "голос-и-память", "05--голос-и-аватар", "голос-и-память-1", "api-v3"
    }


def test_code_fences_are_not_targets_or_headings():
    text = "```md\n# Пример\n[x](missing.md)\n```\n~~~html\n<img src='absent.svg'>\n~~~\n# Настоящий\n"
    assert check_docs.document_targets(text) == []
    assert check_docs.markdown_anchors(text) == {"настоящий"}


def test_picture_sources_and_multiline_images_are_validated():
    text = '<picture>\n<source srcset="dark.svg 1x, dark2.svg 2x">\n<img\n src="light.svg" alt="Iris">\n</picture>'
    assert check_docs.document_targets(text) == [(2, "dark.svg"), (2, "dark2.svg"), (3, "light.svg")]


def test_markdown_reference_links_and_inline_examples():
    text = "[Запуск][start]\n[start]: <guide.md#запуск>\n`[пример](missing.md)`\n"
    assert check_docs.document_targets(text) == [(2, "guide.md#запуск")]


def test_missing_image_and_heading_report_file_and_line(tmp_path, monkeypatch):
    doc = tmp_path / "index.md"
    doc.write_text('# Начало\n<img src="missing.svg">\n[раздел](#нет)\n', encoding="utf-8")
    monkeypatch.setattr(check_docs, "ROOT", tmp_path)
    monkeypatch.setattr(check_docs, "maintained_markdown", lambda: [doc])
    errors = []
    check_docs.check_links(errors)
    assert errors == [
        "index.md:3: missing heading anchor '#нет'",
        "index.md:2: missing local target 'missing.svg'",
    ]


def test_local_link_escape_and_percent_encoded_cyrillic(tmp_path, monkeypatch):
    doc = tmp_path / "index.md"
    (tmp_path / "голос.md").write_text("# Голос\n", encoding="utf-8")
    doc.write_text("[ok](%D0%B3%D0%BE%D0%BB%D0%BE%D1%81.md#голос)\n[x](../outside.md)\n", encoding="utf-8")
    monkeypatch.setattr(check_docs, "ROOT", tmp_path)
    monkeypatch.setattr(check_docs, "maintained_markdown", lambda: [doc])
    errors = []
    check_docs.check_links(errors)
    assert errors == ["index.md:2: link escapes repository: '../outside.md'"]


def test_external_urls_are_not_local_paths(tmp_path, monkeypatch):
    doc = tmp_path / "index.md"
    doc.write_text("[site](https://example.org/a#b)\n<img src='//example.org/logo.svg'>\n", encoding="utf-8")
    monkeypatch.setattr(check_docs, "ROOT", tmp_path)
    monkeypatch.setattr(check_docs, "maintained_markdown", lambda: [doc])
    errors = []
    check_docs.check_links(errors)
    assert errors == []


def test_maintained_inventory_includes_brand_and_developer_guides():
    files = {path.relative_to(check_docs.ROOT).as_posix() for path in check_docs.maintained_markdown()}
    assert {"README.en.md", "README.ru.md", "Docs/index.md", "CONTRIBUTING.md", "assets/README.md", "apps/web/public/brand/README.md"} <= files


def test_readme_language_links_allow_different_heading_structures(tmp_path, monkeypatch):
    (tmp_path / "README.md").write_text("# Ирис\n## Запуск\n[English](./README.en.md)\n", encoding="utf-8")
    (tmp_path / "README.en.md").write_text("# Iris\n[Русский](README.md#ирис)\n", encoding="utf-8")
    (tmp_path / "README.ru.md").write_text("[Русский](README.md)\n", encoding="utf-8")
    monkeypatch.setattr(check_docs, "ROOT", tmp_path)
    errors = []
    check_docs.check_readme_navigation(errors)
    assert errors == []


def test_readme_language_link_cannot_point_to_old_alias_or_external_copy(tmp_path, monkeypatch):
    (tmp_path / "README.md").write_text("[English](https://example.org/README.en.md)\n", encoding="utf-8")
    (tmp_path / "README.en.md").write_text("[Русский](README.ru.md)\n", encoding="utf-8")
    (tmp_path / "README.ru.md").write_text("[Русский](README.md)\n", encoding="utf-8")
    monkeypatch.setattr(check_docs, "ROOT", tmp_path)
    errors = []
    check_docs.check_readme_navigation(errors)
    assert errors == [
        "README.md: missing language link to README.en.md",
        "README.en.md: missing language link to README.md",
    ]


def test_readme_images_cannot_be_replaced_with_plain_links(tmp_path, monkeypatch):
    (tmp_path / "README.md").write_text("[![Диалог](screen.png)](screen.png)\n", encoding="utf-8")
    (tmp_path / "README.en.md").write_text("[Dialogue](screen.png)\n", encoding="utf-8")
    monkeypatch.setattr(check_docs, "ROOT", tmp_path)
    errors = []
    check_docs.check_readme_images(errors)
    assert errors == ["README.en.md: missing shared image screen.png"]


def test_readme_images_allow_translated_captions_and_html(tmp_path, monkeypatch):
    (tmp_path / "README.md").write_text("![Диалог](screen.png)\n```md\n![Пример](ignore.png)\n```\n", encoding="utf-8")
    (tmp_path / "README.en.md").write_text('<details>\n<img src="./screen.png" alt="Dialogue">\n</details>\n', encoding="utf-8")
    monkeypatch.setattr(check_docs, "ROOT", tmp_path)
    errors = []
    check_docs.check_readme_images(errors)
    assert errors == []


def test_readme_images_require_matching_localized_artwork(tmp_path, monkeypatch):
    (tmp_path / "README.md").write_text('![Ирис](header.ru.light.png)\n![Диалог](screen.png)', encoding="utf-8")
    english = tmp_path / "README.en.md"
    english.write_text('![Iris](header.en.light.png)\n![Dialogue](screen.png)', encoding="utf-8")
    monkeypatch.setattr(check_docs, "ROOT", tmp_path)
    errors = []
    check_docs.check_readme_images(errors)
    assert errors == []
    english.write_text('![Dialogue](screen.png)', encoding="utf-8")
    check_docs.check_readme_images(errors)
    assert errors == ["README.en.md: missing shared image header.en.light.png"]
