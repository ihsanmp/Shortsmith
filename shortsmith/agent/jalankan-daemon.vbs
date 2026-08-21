' ---------------------------------------------------------------------------
'  Pembungkus tak terlihat untuk jalankan-daemon.cmd.
'
'  Kenapa ada lapisan ini sama sekali:
'
'  Task Scheduler menjalankan pemicunya tiap lima menit sebagai penjaga kalau
'  daemon mati. Menjalankan berkas .cmd secara langsung membuat jendela konsol
'  berkedip tiap kali - hampir tiga ratus kali sehari di layar pengguna, untuk
'  pemeriksaan yang hampir selalu berakhir "tidak ada yang perlu dilakukan".
'
'  Setelan "Hidden" milik Task Scheduler tidak menyelesaikannya: ia
'  menyembunyikan jendela TUGAS-nya, bukan jendela konsol yang dibuka cmd.exe.
'  WScript.Shell dengan mode jendela 0 memang benar-benar tidak menampilkan
'  apa pun, dan itulah satu-satunya cara yang tidak berkedip.
'
'  Argumen kedua Run adalah 0 (sembunyikan), ketiga False (jangan tunggu):
'  daemon berjalan berjam-jam, dan menunggunya akan membuat Task Scheduler
'  menganggap tugasnya masih berjalan selama itu - yang justru berguna, tapi
'  bukan lewat proses vbs yang menganggur menunggunya.
' ---------------------------------------------------------------------------

Dim shell, folder
Set shell = CreateObject("WScript.Shell")

' Folder skrip ini sendiri, supaya tidak bergantung pada direktori kerja yang
' diwariskan Task Scheduler - yang tidak dijamin apa pun.
folder = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))

shell.Run """" & folder & "jalankan-daemon.cmd""", 0, False
