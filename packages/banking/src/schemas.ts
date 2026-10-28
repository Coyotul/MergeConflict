import { z } from "zod";

export const moneySchema = z.string().regex(/^\d{1,9}(\.\d{1,2})?$/, "Enter a positive decimal amount with at most two decimal places.");
export const documentKindSchema = z.enum(["identity", "income", "statement"]);
export const sessionSchema = z.object({
  role: z.enum(["customer", "reviewer"]),
  email: z.string().trim().max(254).email("Enter a valid demo email address.").toLowerCase(),
  password: z.string().min(1, "Enter your demo password.").max(128),
}).strict();
export const storedSessionSchema = z.object({
  token: z.uuid(),
  actor: z.object({ id: z.string().min(1), name: z.string().min(1), role: z.enum(["customer", "reviewer"]) }).strict(),
  expiresAt: z.iso.datetime(),
}).strict();
export const chatSchema = z.object({ text: z.string().trim().min(1).max(2000) }).strict();
export const createApplicationSchema = z.object({
  amount: moneySchema, months: z.number().int().min(6).max(360),
  productId: z.enum(["personal", "mortgage", "car"]), idempotencyKey: z.uuid(),
}).strict();
export const uploadSchema = z.object({
  kind: documentKindSchema, name: z.string().trim().min(1).max(160).regex(/^[^\\/\x00-\x1f]+$/, "Invalid filename."),
  mimeType: z.enum(["application/pdf", "image/jpeg", "image/png"]), size: z.number().int().positive().max(10 * 1024 * 1024),
  syntheticConfirmed: z.literal(true, { error: "Confirm that the document contains synthetic data only." }),
}).strict().refine((v) => ({ "application/pdf": /\.pdf$/i, "image/jpeg": /\.jpe?g$/i, "image/png": /\.png$/i })[v.mimeType].test(v.name), { message: "File extension must match its type.", path: ["name"] });
export const submitSchema = z.object({ confirmed: z.literal(true), idempotencyKey: z.uuid() }).strict();
export const reviewSchema = z.object({
  action: z.enum(["approve", "reject", "request-information"]), reason: z.string().trim().min(10).max(2000),
  evidenceReviewed: z.literal(true), requestedDocument: documentKindSchema.optional(), idempotencyKey: z.uuid(),
}).strict().refine((v) => v.action !== "request-information" || Boolean(v.requestedDocument), { message: "Choose a document to request.", path: ["requestedDocument"] });
export const noteSchema = z.object({ text: z.string().trim().min(3).max(2000) }).strict();
export const consentSchema = z.object({ financialInsights: z.boolean(), notifications: z.boolean() }).strict();
export const supportSchema = z.object({ message: z.string().trim().min(3).max(2000) }).strict();
export type CreateApplicationInput = z.infer<typeof createApplicationSchema>;
export type SessionInput = z.infer<typeof sessionSchema>;
export type UploadInput = z.infer<typeof uploadSchema>;
export type SubmitInput = z.infer<typeof submitSchema>;
export type ReviewInput = z.infer<typeof reviewSchema>;
