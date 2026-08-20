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
  createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
});

export const projects = pgTable(
  "projects",
  {
    id: uuid("id").primaryKey().defaultRandom(),
    judul: text("judul").notNull().default("Tanpa judul"),
    conceptId: uuid("concept_id")
      .notNull()
      .references(() => conceptProfiles.id, { onDelete: "restrict" }),
    brief: text("brief").notNull().default(""),
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
    heartbeatAt: timestamp("heartbeat_at", { withTimezone: true }),
    startedAt: timestamp("started_at", { withTimezone: true }),
    finishedAt: timestamp("finished_at", { withTimezone: true }),
    createdAt: timestamp("created_at", { withTimezone: true }).notNull().defaultNow(),
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
