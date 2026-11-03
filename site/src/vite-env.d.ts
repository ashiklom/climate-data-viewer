/// <reference types="vite/client" />

declare module "virtual:cds-key" {
  /** Local CDS API key (development server only; builds fail by design). */
  const key: string;
  export default key;
}
