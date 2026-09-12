Ushh Ticket Maker v2

What this version does:
- Uses the supplied finished A4 ticket artwork as the template.
- Supports the Green/Orange and Blue/Pink templates included in /templates.
- Accepts two 6-card number PDFs (one PDF for each half/ticket).
- Reads the supplied numbers; it does NOT generate or randomize numbers.
- Inserts a 6-character ticket code into the existing ticket-code box.
- Places each number into its exact 3 x 9 Tambola grid position.
- Uses bold numbers and the appropriate colour for each ticket side.
- Keeps the existing logos, artwork, headings and card design unchanged.

Important fix in this version:
The previous build used incorrect vertical coordinates between cards, causing numbers to drift into the gaps/header areas. The grid coordinates have been corrected for all six cards.

Run:
  pip install -r requirements.txt
  streamlit run app.py

Then open the local Streamlit URL shown in the terminal.


V9 3-CARD LAYOUT FIX:
- The 3-card template now uses its own exact grid coordinates, so numbers stay inside Card 1, Card 2 and Card 3.
- The 3-card ticket-code position is matched to the lower code box in the 3-card artwork.
- Number colours now match the template header artwork exactly for Green/Orange and Blue/Pink.
- 3-card mode requires exactly 3 input PDF pages; 6-card mode requires exactly 6 pages. This prevents accidentally using a 6-card source in 3-card mode and creating floating/misaligned numbers.

V6 FIX: Batch pair uploader now resets correctly after Add Batch, preventing stale selected PDFs from causing the "select exactly 2 PDFs" warning.
