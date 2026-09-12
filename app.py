
import io
import re
import csv
import zipfile
from pathlib import Path

import fitz  # PyMuPDF
import streamlit as st
from PIL import Image
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import white, black
from pypdf import PdfReader, PdfWriter


st.set_page_config(page_title="Ushh Ticket Maker", page_icon="🎟️", layout="centered")

PAGE_W, PAGE_H = A4

# A4 has two tickets side-by-side. Each ticket can be either 6 cards or 3 cards.
CELL_X_LEFT = [30.8, 60.35, 89.9, 119.45, 149.0, 178.55, 208.1, 237.65, 267.2]

# Centers of the number cells measured from the supplied artwork.
ROW_Y_6 = [
    [717.0, 689.3, 661.7],
    [590.3, 563.0, 535.7],
    [464.3, 437.0, 409.7],
    [338.3, 311.0, 283.7],
    [212.3, 185.0, 157.7],
    [87.0, 59.7, 32.0],
]

# Three-card templates use the upper/middle/lower ticket positions.
ROW_Y_3 = [
    [530.0, 502.0, 474.0],
    [404.0, 376.0, 348.0],
    [278.0, 250.0, 222.0],
]

# The 3-card artwork has its ticket-code box lower on the page than the 6-card artwork.
CODE_Y_6 = PAGE_H - 47
CODE_Y_3 = 618.0
SIDE_OFFSETS = [0, PAGE_W / 2]


def parse_card(page):
    """Extract the 3x9 card from one PDF page without generating any numbers."""
    words = page.get_text("words")

    # Ignore footer/date text. The number grid is above the instruction line.
    enter_y = min(
        [w[1] for w in words if w[4].lower().startswith("enter")],
        default=1000
    )

    nums = []
    for w in words:
        x0, y0, x1, y1, txt, *_ = w
        if y0 > 125 and y0 < enter_y and txt.isdigit():
            value = int(txt)
            if 1 <= value <= 90:
                nums.append((x0, y0, x1, y1, value))

    # Group the extracted numbers into the three visual rows.
    rows = []
    for item in sorted(nums, key=lambda z: z[1]):
        for row in rows:
            if abs(row["y"] - item[1]) < 5:
                row["items"].append(item)
                break
        else:
            rows.append({"y": item[1], "items": [item]})

    rows = sorted(rows, key=lambda r: r["y"])[:3]
    if len(rows) != 3:
        raise ValueError("Could not find exactly 3 number rows on a card page.")

    grid = [[None] * 9 for _ in range(3)]

    for r, row in enumerate(rows):
        for x0, y0, x1, y1, value in sorted(row["items"], key=lambda z: z[0]):
            # Tambola columns: 1–9, 10–19, ..., 70–79, 80–90.
            col = 0 if value < 10 else min(8, value // 10)
            if grid[r][col] is not None:
                raise ValueError(
                    f"Duplicate column detected in row {r + 1}: value {value}."
                )
            grid[r][col] = value

    return grid


def extract_ticket(pdf_bytes, cards_per_ticket):
    """Read exactly the requested number of card pages from the supplied number PDF."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if len(doc) != cards_per_ticket:
        raise ValueError(
            f"This {cards_per_ticket}-card mode requires exactly {cards_per_ticket} card pages. "
            f"The uploaded PDF has {len(doc)} page(s). Please choose the matching {cards_per_ticket}-card PDF."
        )
    return [parse_card(doc[i]) for i in range(cards_per_ticket)]


def make_base_pdf(template_bytes):
    """Return a one-page A4 PDF from either a PDF or an image template."""
    if template_bytes[:4] == b"%PDF":
        doc = fitz.open(stream=template_bytes, filetype="pdf")
        if len(doc) == 0:
            raise ValueError("Template PDF is empty.")
        page = doc[0]
        if abs(page.rect.width - PAGE_W) > 3 or abs(page.rect.height - PAGE_H) > 3:
            raise ValueError("Template must be A4 portrait (595 x 842 pt).")
        return template_bytes

    # Image template fallback.
    img = Image.open(io.BytesIO(template_bytes)).convert("RGB")
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawImage(
        ImageReader(img),
        0, 0,
        width=PAGE_W,
        height=PAGE_H,
        preserveAspectRatio=True,
        anchor="c",
    )
    c.save()
    return buf.getvalue()


def get_number_colors(template_name):
    """Return number/code colors matching the supplied template artwork."""
    name = template_name.lower()
    if "blue_pink" in name or "blue pink" in name:
        return [(0.29411766, 0.62352941, 0.83137255), (0.81568627, 0.51764706, 0.67058824)]
    if "green_orange" in name or "green orange" in name:
        return [(0.03137255, 0.43921569, 0.41567102), (0.8, 0.25490198, 0.23921569)]
    # Safe fallback for a custom template.
    return [(0.02, 0.42, 0.41), (0.78, 0.10, 0.10)]


def build_output(template_bytes, template_name, ticket_a, code_a, ticket_b, code_b):
    """Overlay only the supplied ticket codes and numbers onto the uploaded artwork."""
    base = PdfReader(io.BytesIO(template_bytes))
    if not base.pages:
        raise ValueError("Template PDF has no pages.")

    overlay_buf = io.BytesIO()
    c = canvas.Canvas(overlay_buf, pagesize=A4)

    number_colors = get_number_colors(template_name)
    code_colors = number_colors
    cards_count = len(ticket_a)
    if cards_count not in (3, 6) or len(ticket_b) != cards_count:
        raise ValueError("Both tickets must contain the same number of cards: 3 or 6.")
    row_y = ROW_Y_6 if cards_count == 6 else ROW_Y_3
    code_y = CODE_Y_6 if cards_count == 6 else CODE_Y_3

    for side, (cards, code) in enumerate(((ticket_a, code_a), (ticket_b, code_b))):
        xoff = SIDE_OFFSETS[side]

        # The uploaded template already contains the white ticket-code box
        # and the ":: Ticket Code" label. We only add the user's code in
        # the blank area; the artwork itself is never redrawn.
        c.setFillColorRGB(*code_colors[side])
        c.setFont("Helvetica-Bold", 10.5)
        c.drawString(xoff + 151, code_y, code)

        # Numbers: bold, large, centred in each existing cell.
        c.setFillColorRGB(*number_colors[side])
        c.setFont("Helvetica-Bold", 15.5)
        for card_index, grid in enumerate(cards):
            for row_index, row in enumerate(grid):
                for col_index, value in enumerate(row):
                    if value is not None:
                        c.drawCentredString(
                            CELL_X_LEFT[col_index] + xoff,
                            row_y[card_index][row_index] - 5.5,
                            str(value),
                        )

    c.save()
    overlay_buf.seek(0)

    overlay = PdfReader(overlay_buf)
    page = base.pages[0]
    page.merge_page(overlay.pages[0])

    writer = PdfWriter()
    writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


st.title("🎟️ Ushh Ticket Maker")
st.caption("Use your finished ticket artwork as the template. The app inserts only the supplied numbers and ticket codes.")

st.info(
    "No numbers are generated or randomized. Each uploaded number PDF is read card-by-card "
    "and placed into the matching 3×9 grid."
)

template_dir = Path("templates")
template_files = sorted(
    [p for p in template_dir.glob("*") if p.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg"}]
)

st.subheader("1. Choose your ticket design")

cards_per_ticket = st.radio(
    "Cards per side",
    [6, 3],
    format_func=lambda n: f"{n} cards per side",
    horizontal=True,
    help="Choose 6 for the tall six-card design or 3 for the compact three-card design.",
)

mode = st.radio(
    "Generation mode",
    ["One A4 sheet", "Batch generation"],
    horizontal=True,
)

# Only show templates that match the selected card count.
def template_matches_card_count(path, count):
    name = path.stem.lower()
    if count == 3:
        return "3card" in name or "3_card" in name or "3 card" in name
    return "3card" not in name and "3_card" not in name and "3 card" not in name

matching_templates = [p for p in template_files if template_matches_card_count(p, cards_per_ticket)]

if matching_templates:
    selected = st.selectbox(
        f"{cards_per_ticket}-card template",
        matching_templates,
        format_func=lambda p: p.name,
        key=f"template_{cards_per_ticket}",
    )
    template_bytes = selected.read_bytes()
else:
    selected = None
    uploaded_template = st.file_uploader(
        f"Upload an A4 portrait {cards_per_ticket}-card template (PDF/PNG/JPG)",
        type=["pdf", "png", "jpg", "jpeg"],
        key=f"custom_template_{cards_per_ticket}",
    )
    template_bytes = uploaded_template.getvalue() if uploaded_template else None

if mode == "One A4 sheet":
    st.subheader(f"2. Add the two ticket number PDFs ({cards_per_ticket} cards each)")
    col1, col2 = st.columns(2)
    with col1:
        pdf_a = st.file_uploader(f"Ticket A — {cards_per_ticket}-card PDF", type=["pdf"], key="single_pdf_a")
        code_a = st.text_input("Ticket A code", max_chars=6, placeholder="8W7A2W", key="single_code_a")
    with col2:
        pdf_b = st.file_uploader(f"Ticket B — {cards_per_ticket}-card PDF", type=["pdf"], key="single_pdf_b")
        code_b = st.text_input("Ticket B code", max_chars=6, placeholder="9K3P7M", key="single_code_b")

    st.caption(f"Each number PDF must contain at least {cards_per_ticket} pages: Card 1 through Card {cards_per_ticket}. The two PDFs become the left and right tickets on one A4 sheet.")

    if st.button("Generate A4 Ticket", type="primary", use_container_width=True):
        try:
            if not template_bytes:
                st.error("Choose or upload a template first.")
                st.stop()
            if not pdf_a or not pdf_b:
                st.error(f"Upload both {cards_per_ticket}-card number PDFs.")
                st.stop()
            if not re.fullmatch(r"[A-Za-z0-9]{6}", code_a.strip()):
                st.error("Ticket A code must be exactly 6 letters/numbers.")
                st.stop()
            if not re.fullmatch(r"[A-Za-z0-9]{6}", code_b.strip()):
                st.error("Ticket B code must be exactly 6 letters/numbers.")
                st.stop()

            cards_a = extract_ticket(pdf_a.getvalue(), cards_per_ticket)
            cards_b = extract_ticket(pdf_b.getvalue(), cards_per_ticket)
            output = build_output(
                template_bytes, selected.name if template_files else "custom",
                cards_a, code_a.strip().upper(),
                cards_b, code_b.strip().upper(),
            )

            st.success("A4 ticket generated.")
            st.download_button(
                "⬇️ Download print-ready A4 PDF",
                data=output,
                file_name=f"{code_a.strip().upper()}_{code_b.strip().upper()}_tickets.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"Could not generate the ticket: {e}")
            st.caption("If your PDF format differs from the sample, we can adjust the number-reader.")

else:
    # Batch mode: upload any EVEN number of PDFs together.
    # They are automatically paired in upload order:
    # PDF 1+2 = Batch 1, PDF 3+4 = Batch 2, etc.
    st.subheader("2. Upload number PDFs in bulk")
    st.caption(
        f"Select all your {cards_per_ticket}-card number PDFs at once. The app automatically pairs them in order: "
        "PDF 1 + PDF 2, PDF 3 + PDF 4, PDF 5 + PDF 6, and so on."
    )

    if "ticket_rows" not in st.session_state:
        st.session_state.ticket_rows = []
    if "bulk_uploader_version" not in st.session_state:
        st.session_state.bulk_uploader_version = 0

    uploaded_bulk = st.file_uploader(
        f"Upload multiple {cards_per_ticket}-card PDFs",
        type=["pdf"],
        accept_multiple_files=True,
        key=f"bulk_pair_uploader_{st.session_state.bulk_uploader_version}",
        help=f"Upload 2, 4, 6, 8... PDFs. They are paired automatically in the order shown. Each PDF must contain at least {cards_per_ticket} card pages.",
    )

    def code_from_filename(name):
        """Try to find a 6-character ticket code in a filename."""
        stem = Path(name).stem.upper()
        matches = re.findall(r"(?<![A-Z0-9])[A-Z0-9]{6}(?![A-Z0-9])", stem)
        return matches[0] if matches else ""

    if uploaded_bulk:
        if len(uploaded_bulk) % 2 != 0:
            st.warning(
                f"You selected {len(uploaded_bulk)} PDF(s). Please select an even number of PDFs "
                "because every 2 PDFs make one A4 sheet (LEFT + RIGHT)."
            )
        else:
            pair_count = len(uploaded_bulk) // 2
            st.success(f"{len(uploaded_bulk)} PDFs found → {pair_count} A4 batch(es) ready to add.")
            st.markdown("### Ticket batches to add")
            st.caption("Every batch has its own LEFT and RIGHT ticket-code fields. Check/edit each code before adding.")

            pending = []
            for pair_index in range(pair_count):
                left_file = uploaded_bulk[pair_index * 2]
                right_file = uploaded_bulk[pair_index * 2 + 1]

                st.markdown(f"#### Batch {pair_index + 1}")
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("**LEFT / Ticket A**")
                    st.info(left_file.name)
                    left_code = st.text_input(
                        "Ticket A code",
                        value=code_from_filename(left_file.name),
                        max_chars=6,
                        placeholder="e.g. XC6F87",
                        key=f"bulk_left_code_{st.session_state.bulk_uploader_version}_{pair_index}",
                    )
                with col2:
                    st.markdown("**RIGHT / Ticket B**")
                    st.info(right_file.name)
                    right_code = st.text_input(
                        "Ticket B code",
                        value=code_from_filename(right_file.name),
                        max_chars=6,
                        placeholder="e.g. Q722CU",
                        key=f"bulk_right_code_{st.session_state.bulk_uploader_version}_{pair_index}",
                    )

                pending.append((left_file, left_code, right_file, right_code))
                if pair_index < pair_count - 1:
                    st.divider()

            st.divider()
            if st.button(
                f"➕ Add {pair_count} Batch{'es' if pair_count != 1 else ''}",
                use_container_width=True,
                type="primary",
            ):
                errors = []
                validated = []
                for i, (left_file, left_code, right_file, right_code) in enumerate(pending, start=1):
                    ca = left_code.strip().upper()
                    cb = right_code.strip().upper()
                    if not re.fullmatch(r"[A-Za-z0-9]{6}", ca):
                        errors.append(f"Batch {i}: Ticket A code must be exactly 6 letters/numbers.")
                    if not re.fullmatch(r"[A-Za-z0-9]{6}", cb):
                        errors.append(f"Batch {i}: Ticket B code must be exactly 6 letters/numbers.")
                    validated.append((left_file, ca, right_file, cb))

                if errors:
                    for error in errors:
                        st.error(error)
                else:
                    for left_file, ca, right_file, cb in validated:
                        st.session_state.ticket_rows.append({
                            "left_pdf": left_file.getvalue(),
                            "left_name": left_file.name,
                            "left_code": ca,
                            "right_pdf": right_file.getvalue(),
                            "right_name": right_file.name,
                            "right_code": cb,
                        })
                    # Reset the uploader and code fields for the next bulk upload.
                    st.session_state.bulk_uploader_version += 1
                    st.rerun()

    if st.session_state.ticket_rows:
        st.subheader("3. Ticket list")
        st.caption("Review the batches before generating. Each row = one A4 sheet = 2 tickets = 12 cards.")

        header = st.columns([0.5, 2.3, 1.0, 2.3, 1.0, 0.9, 0.7])
        for col, label in zip(header, ["#", "Left PDF", "Left Code", "Right PDF", "Right Code", "Status", ""]):
            col.markdown(f"**{label}**")

        for i, row in enumerate(st.session_state.ticket_rows):
            cols = st.columns([0.5, 2.3, 1.0, 2.3, 1.0, 0.9, 0.7])
            cols[0].write(i + 1)
            cols[1].write(row["left_name"])
            cols[2].write(row["left_code"])
            cols[3].write(row["right_name"])
            cols[4].write(row["right_code"])
            cols[5].write("Ready")
            if cols[6].button("✕", key=f"delete_batch_{i}", help=f"Delete batch {i + 1}"):
                st.session_state.ticket_rows.pop(i)
                st.rerun()

        st.divider()
        st.write(
            f"**{len(st.session_state.ticket_rows)} A4 sheet(s)** • "
            f"**{len(st.session_state.ticket_rows) * 2} tickets** • "
            f"**{len(st.session_state.ticket_rows) * cards_per_ticket * 2} cards**"
        )
        if st.button("🗑️ Clear All Batches", use_container_width=True):
            st.session_state.ticket_rows = []
            st.rerun()

    st.subheader("4. Generate")
    if st.button("🚀 Generate All A4 Tickets", type="primary", use_container_width=True):
        try:
            if not template_bytes:
                st.error("Choose or upload a template first.")
                st.stop()
            rows = st.session_state.ticket_rows
            if not rows:
                st.error("Add at least one batch first.")
                st.stop()

            outputs = []
            progress = st.progress(0)
            status = st.empty()
            total = len(rows)

            for i, row in enumerate(rows, start=1):
                ca, cb = row["left_code"], row["right_code"]
                status.write(f"Generating sheet {i} of {total}: {ca} + {cb}")
                cards_a = extract_ticket(row["left_pdf"], cards_per_ticket)
                cards_b = extract_ticket(row["right_pdf"], cards_per_ticket)
                pdf_bytes = build_output(template_bytes, selected.name if template_files else "custom", cards_a, ca, cards_b, cb)
                filename = f"{i:04d}_{ca}_{cb}.pdf"
                outputs.append((filename, pdf_bytes))
                progress.progress(i / total)

            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for filename, pdf_bytes in outputs:
                    zf.writestr(filename, pdf_bytes)
            zip_buf.seek(0)

            combined = PdfWriter()
            for _, pdf_bytes in outputs:
                reader = PdfReader(io.BytesIO(pdf_bytes))
                for page in reader.pages:
                    combined.add_page(page)
            combined_buf = io.BytesIO()
            combined.write(combined_buf)
            combined_buf.seek(0)

            status.success(f"Done — generated {total} A4 sheets ({total * 2} tickets / {total * cards_per_ticket * 2} cards).")
            st.download_button(
                "⬇️ Download ALL individual A4 PDFs (ZIP)",
                data=zip_buf.getvalue(),
                file_name="ushh_ticket_batch.zip",
                mime="application/zip",
                use_container_width=True,
            )
            st.download_button(
                "⬇️ Download ONE combined print PDF",
                data=combined_buf.getvalue(),
                file_name="ushh_ticket_batch_combined.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        except Exception as e:
            st.error(f"Batch generation failed: {e}")

    with st.expander("How this works"):
        st.markdown(
            f"""
            **Bulk workflow:**
            1. Select all your {cards_per_ticket}-card number PDFs at once — 2, 4, 6, 8, etc.
            2. The app automatically pairs them in order: 1+2, 3+4, 5+6, etc.
            3. Each pair gets its own **Ticket A code** and **Ticket B code** field.
            4. Click **Add Batches** once to add all pairs to the ticket list.
            5. Delete any unwanted row from the list if necessary.
            6. Click **Generate All A4 Tickets**.

            The app never generates or randomizes numbers. It reads the numbers from your PDFs and places them in the matching 3×9 cells. Choose either 6-card or 3-card artwork before generating.
            """
        )

with st.expander("Current rules"):
    st.write(
        "• 3 or 6 cards per ticket • 3×9 grid • 6-character ticket codes • numbers are extracted from your PDFs only • "
        "template artwork/logos/headings stay unchanged • no number generation or randomization."
    )
