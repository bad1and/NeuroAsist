from huggingface_hub import snapshot_download


snapshot_download(
    repo_id="ResembleAI/chatterbox",
    allow_patterns=[
        "ve.pt",
        "t3_mtl23ls_v3.safetensors",
        "s3gen.pt",
        "grapheme_mtl_merged_expanded_v1.json",
        "conds.pt",
        "Cangjie5_TC.json",
    ],
)
