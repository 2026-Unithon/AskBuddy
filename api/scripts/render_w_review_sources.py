"""이미 보존한 dev 검토 packet의 원본 PDF·영상 근거를 로컬 렌더한다."""
import argparse
import json
import subprocess
from pathlib import Path
import pypdfium2 as pdfium

API=Path(__file__).resolve().parents[1]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("packet_dir",type=Path)
    args=ap.parse_args()
    directory=args.packet_dir.resolve()
    if not directory.is_relative_to(API/"eval/reports"):
        ap.error("Git 제외 dev 검토 디렉터리만 허용")
    output=directory/"source_qa"
    output.mkdir(exist_ok=False)
    packet=json.loads((directory/"review_packet.json").read_text())
    entries=[*packet["covered_sample"],*packet["all_undetermined"]]
    text_sources={}
    for slug in ("eval-a","eval-b"):
        current=json.loads((directory/f"current_{slug}.json").read_text())
        base=API/"eval/data"/slug.replace("eval-","store-")
        for source in current["manifest"]["sources"]:
            key=source["source_key"]
            selected=[e for e in entries if e["store"]==slug and e["truth"]["source_key"]==key]
            if not selected:
                continue
            path=base/source["file"]
            if path.suffix==".pdf":
                doc=pdfium.PdfDocument(str(path))
                texts=[]
                for index in range(len(doc)):
                    page=doc[index]
                    texts.append(page.get_textpage().get_text_range())
                    page.render(scale=1.5).to_pil().save(output/f"{key}_page{index+1}.png")
                    page.close()
                doc.close()
                text_sources[key]=dict(type="PDF",pages=texts)
            elif source["type"]=="KAKAO":
                text_sources[key]=dict(type="KAKAO",text=path.read_text())
            elif source["type"]=="VIDEO":
                for entry in selected:
                    locator=entry["truth"].get("locator",{})
                    timestamp=locator.get("timestamp_sec")
                    if timestamp is None:
                        continue
                    target=output/f"{entry['truth']['fact_id']}_t{timestamp}.png"
                    subprocess.run(["ffmpeg","-v","error","-ss",str(timestamp),"-i",str(path),
                                    "-frames:v","1","-vf","scale=960:-1",str(target)],check=True)
        for original in current["originals"]:
            text_sources[original["source_key"]]=original
    with (output/"source_text.json").open("x",encoding="utf-8") as file:
        json.dump(text_sources,file,ensure_ascii=False,indent=2)
    print(f"PDF/영상 원본 렌더와 보존 전사문: {output}")


if __name__=="__main__":
    main()
