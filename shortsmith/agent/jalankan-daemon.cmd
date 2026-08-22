@echo off
REM ---------------------------------------------------------------------------
REM  Penyala daemon Shortsmith, dipakai oleh Windows Task Scheduler.
REM
REM  Kenapa lewat berkas .cmd dan bukan langsung python.exe di Task Scheduler:
REM  aksi Task Scheduler tidak bisa mengalihkan stdout/stderr ke berkas. Tanpa
REM  pengalihan itu, seluruh log daemon hilang begitu saja - dan log itulah
REM  satu-satunya cara tahu kenapa sebuah job gagal.
REM ---------------------------------------------------------------------------

cd /d "%~dp0"

REM --- Penjaga instance tunggal -----------------------------------------------
REM
REM Setelan MultipleInstances milik Task Scheduler TIDAK cukup: ia hanya
REM mengenali instance yang dijalankan Task Scheduler sendiri. Daemon yang
REM dinyalakan tangan dari terminal tidak terlihat olehnya, sehingga pemicu
REM berulang akan menumpuk daemon kedua di atas yang sedang mengerjakan job.
REM
REM Path powershell ditulis TANPA kutip. Ia memang tidak memuat spasi, dan baris
REM batch yang diawali path berkuotasi lalu memuat kutip lagi di belakangnya
REM dipotong cmd di tempat yang salah - terbukti gagal dengan pesan
REM '"C:\WINDOWS\System32\WindowsPowerShell' is not recognized.
REM
REM Di dalam perintahnya hanya dipakai kutip TUNGGAL, karena kutip ganda
REM bersarang di satu baris batch adalah sumber kegagalan yang sama.
REM Disaring ke python.exe SAJA, dan itu bukan sekadar penghematan.
REM
REM Tanpa saringan itu, penjaga ini menemukan DIRINYA SENDIRI: proses
REM powershell yang menjalankan pemeriksaan membawa pola pencariannya di
REM command line-nya sendiri, sehingga pencarian selalu menemukan satu
REM kecocokan. Akibatnya launcher selalu menyimpulkan daemon sudah jalan,
REM selalu keluar, dan daemon TIDAK PERNAH menyala.
REM
REM Terbukti saat diuji: pola '*POLA-XYZ*' yang mustahil cocok pun
REM mengembalikan dua kecocokan.
%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "if (Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -like '*shortsmith.cli daemon*' }) { exit 1 } else { exit 0 }"

REM Dibandingkan PERSIS dengan 1, bukan `if errorlevel 1`.
REM
REM `if errorlevel 1` bernilai benar untuk SEMUA kode >= 1, termasuk 9009 yang
REM berarti powershell sendiri tidak ditemukan. Dengan bentuk itu, penjaga yang
REM rusak membuat launcher selalu keluar diam-diam dan daemon TIDAK PERNAH
REM menyala - kegagalan yang jauh lebih buruk daripada yang ia cegah.
REM
REM Arah amannya sengaja dipilih: kalau penjaga tidak bisa memastikan, daemon
REM tetap dinyalakan. Daemon ganda merepotkan; daemon yang tidak pernah hidup
REM membuat seluruh sistem diam tanpa ada yang tahu.
if "%ERRORLEVEL%"=="1" exit /b 0

set "LOG=%~dp0daemon.err"
set "OUT=%~dp0daemon.out"

REM --- Rotasi log --------------------------------------------------------------
REM
REM Decoder h264 menulis ribuan baris peringatan "mmco: unref short failure"
REM untuk tiap video yang dibaca. Dibiarkan menyambung terus, berkasnya tumbuh
REM ratusan MB dan justru jadi tidak terbaca saat dibutuhkan.
REM
REM Satu salinan lama disimpan: cukup untuk melihat apa yang terjadi sebelum
REM daemon terakhir kali mati, tanpa menumpuk tanpa batas.
if exist "%LOG%" (
  for %%A in ("%LOG%") do if %%~zA GTR 20000000 (
    if exist "%LOG%.1" del "%LOG%.1"
    move /y "%LOG%" "%LOG%.1" >nul
  )
)

REM Ditambahkan, bukan ditimpa: menimpa akan menghapus jejak kematian
REM sebelumnya - justru bagian yang paling perlu dibaca.
"%~dp0.venv\Scripts\python.exe" -m shortsmith.cli daemon >>"%OUT%" 2>>"%LOG%"
