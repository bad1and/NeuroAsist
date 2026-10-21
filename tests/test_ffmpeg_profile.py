from scripts.check_ffmpeg_profile import profile_issues


PROFILE = {"ffmpeg_version": "8.1.2"}
SAFE = {"license": "LGPL version 2.1 or later", "configuration": "--enable-shared --disable-gpl --disable-nonfree --disable-autodetect"}


def test_lgpl_label_does_not_hide_restricted_codec_flags():
    actual = {**SAFE, "configuration": SAFE["configuration"] + " --enable-libx264 --enable-libx265"}
    assert any("libx264" in issue for issue in profile_issues("8.1.2", {"avcodec": actual}, PROFILE))


def test_missing_metadata_and_unknown_version_cannot_pass():
    assert len(profile_issues("unknown", {}, PROFILE)) == 2


def test_no_false_approval_for_missing_explicit_build_flags():
    actual = {**SAFE, "configuration": "--enable-shared"}
    assert profile_issues("8.1.2", {"avcodec": actual}, PROFILE)


def test_selected_profile_flags_match_without_granting_distribution_rights():
    assert profile_issues("8.1.2", {"avcodec": SAFE}, PROFILE) == []
