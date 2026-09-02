import {
  boolean,
  index,
  integer,
  jsonb,
  numeric,
  pgEnum,
  pgTable,
  text,
  timestamp,
  uuid,
} from "drizzle-orm/pg-core";

export const jobStatus = pgEnum("job_status", [
  "pending",
  "processing",
  "done",
  "failed",
]);

export const jobType = pgEnum("job_type", ["render", "profile_extraction"]);

export const assetKind = pgEnum("asset_kind", ["raw", "sample", "output", "music"]);

/**
 * Jenis video yang dituju.
 *
 * Ini BUKAN label. Tiap jenis memilih rasio, durasi target, dan apakah subtitle
 * dibakar — tiga hal yang memang sudah bisa dikendalikan pipeline. Yang belum
 * dikendalikannya adalah gaya potongannya sendiri; itu tetap datang dari konsep.
 */
// AMV pernah ada di sini dan dibuang: ia satu-satunya jenis yang digerakkan
// lagu dan bukan ucapan, dan program ini tidak lagi mengeditnya. Nilainya ikut
// dicabut dari enum Postgres lewat scripts/migrasi-hapus-amv.ts -- bukan
// sekadar dari daftar ini -- supaya tidak ada yang bisa menuliskannya kembali
// lewat jalur lain.
export const videoJenis = pgEnum("video_jenis", ["short", "cinematic", "podcast"]);

/**
 * Permintaan kecil ke agent yang BUKAN render.
 *
 * `prompt`  - Claude menuliskan prompt Google Flow dari bahan yang dipilih.
 * `review`  - Claude memeriksa klip hasil generate terhadap bahan itu.
 */
export const tugasTipe = pgEnum("tugas_tipe", ["prompt", "review"]);

/**
 * Akun pengguna.
 *
 * Pendaftaran dijaga kata sandi undangan (`APP_PASSWORD`), jadi tabel ini hanya
 * berisi orang yang sudah diberi kata sandi itu — bukan siapa pun yang
 * menemukan URL-nya.
 *
 * Tidak ada kolom nama atau foto. Keduanya belum dipakai di mana pun, dan kolom
 * kosong yang menunggu dipakai suatu hari nanti hanya menambah tempat untuk
 * salah.
 */
export const users = pgTable("users", {
  id: uuid("id").primaryKey().defaultRandom(),
  /** Disimpan huruf kecil semua — pencarian email harus buta huruf besar. */
  email: text("email").notNull().unique(),
  /** Bentuk `pbkdf2$<iterasi>$<garam>$<hash>`; lihat lib/sandi.ts. */
  passwordHash: text("password_hash").notNull(),
  /**
   * Nama tampilan. Bawaannya "user" — bukan kosong dan bukan potongan email.
   *
   * Kosong memaksa setiap tempat yang menampilkannya menyediakan cadangannya
   * sendiri, dan cadangan yang tersebar akhirnya berbeda-beda. Potongan email
   * terlihat seperti pilihan yang pernah dibuat pengguna, padahal tidak — dan
   * ia membocorkan alamat email ke layar yang mungkin sedang dibagikan.
   */
  username: text("username").notNull().default("user"),
  /** Storage key foto profil; null berarti pakai avatar gambar bawaan. */
  avatarKey: text("avatar_key"),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  lastLoginAt: timestamp("last_login_at", { withTimezone: true }),
});

/**
 * Catatan perangkat yang sedang masuk.
 *
 * ## Kenapa ini ada padahal sesinya tidak butuh server
 *
 * Cookie sesi membuktikan dirinya sendiri lewat tanda tangan — memverifikasinya
 * tidak perlu menyentuh database sama sekali, dan itu yang membuat middleware
 * bisa berjalan di Edge. Tabel ini TIDAK dipakai untuk memutuskan sah atau
 * tidak; ia murni catatan supaya halaman "Kelola akun" bisa menjawab "di mana
 * saja akun ini sedang terbuka".
 *
 * Konsekuensinya jujur: menghapus baris di sini tidak menendang perangkatnya
 * keluar, karena cookie-nya tetap sah sampai kedaluwarsa sendiri.
 */
export const sessions = pgTable(
  "sessions",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    userId: uuid("user_id")
      .notNull()
      .references(() => users.id, { onDelete: "cascade" }),
    /** User-Agent mentah, dipakai untuk menebak nama browser dan sistemnya. */
    userAgent: text("user_agent").notNull().default(""),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
    lastSeenAt: timestamp("last_seen_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [index("sessions_user_idx").on(t.userId)],
);

/** Concept profile — inti dari "ganti konsep tanpa ubah kode". */
export const conceptProfiles = pgTable("concept_profiles", {
  id: uuid("id").primaryKey().defaultRandom(),
  nama: text("nama").notNull(),
  /** Bentuknya persis ConceptProfile di agent/shortsmith/models.py */
  profileJson: jsonb("profile_json").notNull(),
  sampleVideoUrls: text("sample_video_urls").array().notNull().default([]),
  isDefault: boolean("is_default").notNull().default(false),
  siap: boolean("siap").notNull().default(false),

  // Disembunyikan dari daftar pilihan, TANPA menghapus barisnya.
  //
  // Konsep yang masih dipakai project tidak bisa dihapus — `projects.concept_id`
  // memakai onDelete: "restrict", supaya merapikan daftar konsep tidak pernah
  // melenyapkan project beserta hasil rendernya. Tapi yang diinginkan pengguna
  // saat menekan Hapus biasanya "jangan tampilkan lagi", bukan "musnahkan".
  //
  // Arsip memberi itu tanpa menyentuh satu pun project.
  arsip: boolean("arsip").notNull().default(false),
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});

export const projects = pgTable(
  "projects",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    judul: text("judul").notNull().default("Tanpa judul"),
    // Boleh NULL, dan hilangnya konsep TIDAK menghapus project.
    //
    // Dulu NOT NULL dengan onDelete: "restrict", jadi konsep yang pernah
    // dipakai tidak bisa dihapus selamanya — dan satu-satunya jalan keluar yang
    // ditawarkan adalah menghapus project beserta hasil rendernya.
    //
    // Yang sebenarnya dibutuhkan project dari konsep cuma profilnya, dan itu
    // sekarang disalin ke `profilJson` di bawah. Tautannya tinggal keterangan
    // asal-usul, bukan penopang.
    conceptId: uuid("concept_id").references(() => conceptProfiles.id, {
      onDelete: "set null",
    }),

    // Salinan profil konsep pada saat project ini dibuat.
    //
    // Bukan sekadar supaya konsepnya bisa dihapus. Ia juga MENGUNCI arti
    // project: sebelum ini, mengedit konsep diam-diam mengubah gaya project
    // lama kalau dirender ulang, padahal project itu dibuat dengan angka yang
    // berbeda. Sekarang tiap project mengingat gaya yang benar-benar dipakainya.
    profilJson: jsonb("profil_json").$type<Record<string, unknown>>(),

    // Nama konsepnya saat itu, untuk ditampilkan setelah konsepnya hilang.
    konsepNama: text("konsep_nama"),

    brief: text("brief").notNull().default(""),

    /**
     * Empat komponen brief yang wajib terpenuhi kalau diisi: narasi, kesan,
     * tujuan campaign, dan CTA. Lihat `Arahan` di agent/shortsmith/models.py.
     *
     * Satu kolom jsonb, bukan empat kolom text. Keempatnya selalu diisi,
     * dibaca, dan dikirim bersama sebagai satu formulir — tidak ada satu pun
     * kueri yang menanyakan salah satunya sendirian. Empat kolom berarti empat
     * migrasi untuk satu gagasan.
     *
     * NULL berarti tidak diisi, dan itu keadaan biasa: seluruh alur lama
     * (pencarian topik, pilihan topik) berjalan persis seperti sebelumnya.
     */
    arahan: jsonb("arahan").$type<{
      narasi?: string;
      kesan?: string;
      tujuan?: string;
      cta?: string;
    }>(),

    jenis: videoJenis("jenis").notNull().default("short"),
    /**
     * Rasio keluaran yang DIPILIH pengguna, atau "auto".
     *
     * Text, bukan enum: daftar rasio hidup di agent, dan menambah satu di sana
     * tidak boleh menuntut migrasi database. "auto" berarti serahkan pada jenis
     * dan konsep — perilaku sebelum kolom ini ada.
     */
    rasio: text("rasio").notNull().default("auto"),
    status: jobStatus("status").notNull().default("pending"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [index("projects_created_idx").on(t.createdAt)],
);

/**
 * Info yang DILAPORKAN agent ke server.
 *
 * Halaman web tidak bisa membaca disk pengguna — pembatasan keamanan browser
 * yang tidak bisa dilewati. Supaya form tetap bisa menampilkan daftar folder
 * yang sebenarnya ada, agent-lah yang mengirimkannya ke sini secara berkala.
 * Arah komunikasinya tetap sama seperti sisa sistem: selalu agent -> cloud.
 */
export const agentInfo = pgTable("agent_info", {
  kunci: text("kunci").primaryKey(),
  data: jsonb("data").notNull(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).notNull().defaultNow(),
});

export const assets = pgTable(
  "assets",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    projectId: uuid("project_id").references(() => projects.id, { onDelete: "cascade" }),
    conceptId: uuid("concept_id").references(() => conceptProfiles.id, {
      onDelete: "cascade",
    }),
    jenis: assetKind("jenis").notNull(),

    // Teks yang ditempel saat mengunggah klip ini: pembuka, ringkas isinya,
    // tagar. Ditulis agent dari ucapan di dalam klipnya sendiri.
    //
    // Namanya BUKAN "caption" dengan sengaja: di aplikasi ini caption sudah
    // berarti subtitle yang dibakar ke gambar (lihat CaptionStyle), dan dua hal
    // berbeda dengan satu nama adalah cara paling mudah menyalakan bug yang
    // tidak terlihat.
    keterangan: text("keterangan"),
    /**
     * Urutan file di dalam satu project. Ini DATA, bukan efek samping urutan
     * insert — dan itu perbedaan yang mahal.
     *
     * Sebelum kolom ini ada, agent mengurutkan dengan `ORDER BY created_at, id`.
     * Keempat baris disisipkan dalam satu batch, sehingga `now()` memberi
     * created_at yang identik untuk semuanya, dan penentu akhirnya jatuh ke `id`
     * — sebuah UUID acak. Akibatnya nomor VIDEO diundi ulang tiap project:
     * rekaman suara yang dipilih pengguna bisa mendarat sebagai VIDEO 2, dan
     * klip B-roll jadi sumber suara. Seluruh video salah, tanpa satu pun error.
     */
    urutan: integer("urutan").notNull().default(0),
    /**
     * Berkas ini ada di disk PC pengguna, bukan di object storage.
     *
     * Video mentah sebelumnya selalu menempuh jalur memutar: browser
     * mengunggahnya ke Backblaze, lalu agent DI PC YANG SAMA mengunduhnya
     * kembali. Satu berkas 388 MB berkeliling internet untuk berpindah antar
     * folder di disk yang sama, dan itulah yang menghabiskan kuota harian.
     *
     * Saat `lokal` bernilai true, `storage_key` kosong dan `nama_file` menjadi
     * satu-satunya penunjuk berkas — agent mencarinya di SHORTSMITH_BAHAN_DIR.
     */
    lokal: boolean("lokal").notNull().default(false),
    /**
     * Subfolder di dalam SHORTSMITH_BAHAN_DIR tempat berkas ini berada.
     * Kosong berarti langsung di folder akarnya.
     *
     * Disimpan PER BERKAS, bukan per project. Sempat sebaliknya, dengan alasan
     * "seluruh bahan satu project datang dari satu tempat" — dan itu keliru:
     * rekaman suara dan klip B-roll punya peran berbeda, jadi wajar disimpan di
     * folder berbeda. Satu kolom di project memaksa keduanya berbagi tempat.
     */
    bahanFolder: text("bahan_folder").notNull().default(""),
    /** Key di object storage, bukan URL penuh — URL selalu ditandatangani saat dibutuhkan. */
    storageKey: text("storage_key").notNull(),
    namaFile: text("nama_file").notNull().default(""),
    checksum: text("checksum"),
    durasi: numeric("durasi", { precision: 10, scale: 3 }),
    ukuranBytes: integer("ukuran_bytes"),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [index("assets_project_idx").on(t.projectId)],
);

/**
 * Dua tipe job berbagi satu tabel dan satu mekanisme antrean:
 * `render` untuk membuat short video, `profile_extraction` untuk menganalisis
 * video contoh menjadi concept profile.
 */
/**
 * Antrean permintaan singkat ke agent, terpisah dari `jobs`.
 *
 * ## Kenapa tabel sendiri, bukan satu tipe baru di `jobs`
 *
 * Dua alasan yang sama-sama menghalangi:
 *
 *  1. **Waktunya.** Permintaan prompt terjadi saat pengguna masih MENGISI form
 *     — project-nya belum ada. `jobs` bersandar pada `projectId` atau
 *     `conceptId` untuk tahu apa yang harus dikerjakan, dan keduanya null di
 *     sini.
 *  2. **Muatannya.** `jobs` tidak menyimpan payload sama sekali; `/api/jobs/next`
 *     merakitnya dari project dan assets tiap kali diminta. Permintaan di sini
 *     justru payload itu sendiri, dan jawabannya juga.
 *
 * Menyatukannya berarti menambah dua kolom jsonb yang selalu null untuk setiap
 * job render, plus percabangan di setiap tempat yang membaca antrean.
 */
export const tugas = pgTable(
  "tugas",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    tipe: tugasTipe("tipe").notNull(),
    status: jobStatus("status").notNull().default("pending"),
    /** Apa yang diminta: jenis, tema, daftar bahan, prompt asli, dan seterusnya. */
    permintaan: jsonb("permintaan").notNull(),
    /** Jawaban agent. Null selama belum selesai. */
    hasil: jsonb("hasil"),
    errorMessage: text("error_message"),
    /**
     * Pemiliknya. Hasil tugas hanya boleh dibaca orang yang memintanya —
     * prompt dan klip yang diperiksa adalah isi project yang belum jadi.
     */
    userId: uuid("user_id").references(() => users.id, { onDelete: "cascade" }),
    heartbeatAt: timestamp("heartbeat_at", { withTimezone: true }),
    finishedAt: timestamp("finished_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [index("tugas_queue_idx").on(t.status, t.createdAt)],
);

export const jobs = pgTable(
  "jobs",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    projectId: uuid("project_id").references(() => projects.id, { onDelete: "cascade" }),
    conceptId: uuid("concept_id").references(() => conceptProfiles.id, {
      onDelete: "cascade",
    }),
    tipe: jobType("tipe").notNull(),
    status: jobStatus("status").notNull().default("pending"),
    progress: integer("progress").notNull().default(0),
    tahap: text("tahap").notNull().default(""),
    errorMessage: text("error_message"),
    retryCount: integer("retry_count").notNull().default(0),

    // Berapa kali job ini direbut kembali karena agent-nya berhenti berdenyut.
    //
    // TERPISAH dari retryCount, dan itu bukan kerapian: keduanya menjawab
    // pertanyaan yang berbeda. retryCount menjawab "apakah job ini rusak?",
    // dengan bukti berupa laporan gagal dari agent. lepasCount menjawab
    // "apakah agent-nya sehat?", dan agent yang hilang tidak mengatakan apa pun
    // tentang job-nya. Lihat MAX_LEPAS di lib/queue-sql.ts.
    lepasCount: integer("lepas_count").notNull().default(0),

    heartbeatAt: timestamp("heartbeat_at", { withTimezone: true }),
    startedAt: timestamp("started_at", { withTimezone: true }),
    finishedAt: timestamp("finished_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),

    // Pilihan topik, dipakai saat kolom topik dikosongkan pengguna.
    //
    // Agent membaca topik apa saja yang ada di rekaman, menaruhnya di
    // `topikUsul`, lalu MENUNGGU sampai `topikPilih` terisi. Selama menunggu
    // job tetap `processing` dan agent tetap berdenyut — jadi pembebas job
    // terlantar benar untuk tidak merebutnya.
    //
    // `topikPilih` NULL berarti belum dijawab; array kosong berarti pengguna
    // sengaja tidak memilih satu pun, dan itu jawaban yang sah.
    topikUsul: jsonb("topik_usul").$type<string[]>(),
    topikPilih: jsonb("topik_pilih").$type<string[]>(),
  },
  (t) => [
    // Antrean selalu dibaca dengan filter status + urut created_at.
    index("jobs_queue_idx").on(t.status, t.createdAt),
    index("jobs_heartbeat_idx").on(t.heartbeatAt),
  ],
);

export type ConceptProfileRow = typeof conceptProfiles.$inferSelect;
export type ProjectRow = typeof projects.$inferSelect;
export type AssetRow = typeof assets.$inferSelect;
export type JobRow = typeof jobs.$inferSelect;
