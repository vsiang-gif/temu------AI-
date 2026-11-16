import {
  boolean,
  integer,
  pgTable,
  serial,
  text,
  timestamp,
  unique,
} from 'drizzle-orm/pg-core'

export const admins = pgTable('admins', {
  id: serial('id').primaryKey(),
  username: text('username').notNull().unique(),
  passwordHash: text('password_hash').notNull(),
  createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
})

export const adminSessions = pgTable('admin_sessions', {
  tokenHash: text('token_hash').primaryKey(),
  adminId: integer('admin_id').notNull(),
  expiresAt: timestamp('expires_at', { withTimezone: true }).notNull(),
  createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
})

export const appSettings = pgTable('app_settings', {
  key: text('key').primaryKey(),
  value: text('value').notNull(),
  updatedAt: timestamp('updated_at', { withTimezone: true }).notNull().defaultNow(),
})

export const licenseKeys = pgTable('license_keys', {
  id: serial('id').primaryKey(),
  code: text('code').notNull().unique(),
  note: text('note').notNull().default(''),
  status: text('status').notNull().default('active'),
  durationDays: integer('duration_days'),
  maxDevices: integer('max_devices').notNull().default(1),
  geminiEnabled: boolean('gemini_enabled').notNull().default(true),
  geminiDailyLimit: integer('gemini_daily_limit'),
  activatedAt: timestamp('activated_at', { withTimezone: true }),
  expiresAt: timestamp('expires_at', { withTimezone: true }),
  lastSeenAt: timestamp('last_seen_at', { withTimezone: true }),
  createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
})

export const devices = pgTable(
  'devices',
  {
    id: serial('id').primaryKey(),
    licenseId: integer('license_id').notNull(),
    machineId: text('machine_id').notNull(),
    machineName: text('machine_name').notNull().default(''),
    lastIp: text('last_ip').notNull().default(''),
    firstSeenAt: timestamp('first_seen_at', { withTimezone: true }).notNull().defaultNow(),
    lastSeenAt: timestamp('last_seen_at', { withTimezone: true }).notNull().defaultNow(),
  },
  (t) => [unique().on(t.licenseId, t.machineId)],
)

export const clientSessions = pgTable('client_sessions', {
  tokenHash: text('token_hash').primaryKey(),
  licenseId: integer('license_id').notNull(),
  deviceId: integer('device_id').notNull(),
  expiresAt: timestamp('expires_at', { withTimezone: true }).notNull(),
  createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
})

export const usageLogs = pgTable('usage_logs', {
  id: serial('id').primaryKey(),
  licenseId: integer('license_id').notNull(),
  kind: text('kind').notNull(),
  detail: text('detail').notNull().default(''),
  createdAt: timestamp('created_at', { withTimezone: true }).notNull().defaultNow(),
})

export type LicenseKey = typeof licenseKeys.$inferSelect
export type Device = typeof devices.$inferSelect
