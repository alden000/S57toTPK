# User guide sources

`guide.html` + `img/` render to `User Guide.pdf`. The `{{EXAMPLE}}` placeholder
takes a measured timing example:

```
cd docs/user-guide
python make_pdf.py guide.html "User Guide.pdf" "Rhode Island, USA: 43 charts, ..."
```

The release ZIP holds `S57toTPK.exe` (renamed from the CI artifact), `User Guide.pdf`,
`READ ME FIRST.txt` (CRLF line endings) and `Sample packages/`.
