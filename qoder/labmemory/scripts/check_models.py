from fastembed import TextEmbedding

for m in TextEmbedding.list_supported_models():
    name = m.get("model", "")
    if any(k in name.lower() for k in ["multilingual", "bge-small-zh", "e5"]):
        print(name, "| dim:", m.get("dim"), "| size_gb:", m.get("size_in_GB"))
