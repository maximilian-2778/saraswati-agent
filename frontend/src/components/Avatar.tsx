import { useState } from "react";

export function Avatar({ value, fallback }: { value: string; fallback: string }) {
  return <div className={`avatar${value ? " has-image" : ""}`}>{value ? <img src={value} alt="" /> : fallback}</div>;
}

export function AvatarPicker({ value, fallback, onChange }: {
  value: string;
  fallback: string;
  onChange: (value: string) => void;
}) {
  const [fileError, setFileError] = useState("");

  async function choose(file: File | undefined) {
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      setFileError("请选择图片文件");
      return;
    }
    if (file.size > 1_500_000) {
      setFileError("图片不能超过 1.5 MB");
      return;
    }
    setFileError("");
    onChange(await fileToDataUrl(file));
  }

  return <div className="avatar-picker">
    <Avatar value={value} fallback={fallback} />
    <div>
      <label>选择图片<input type="file" accept="image/png,image/jpeg,image/webp,image/gif" onChange={(event) => void choose(event.target.files?.[0])} /></label>
      {value && <button type="button" onClick={() => onChange("")}>移除</button>}
      {fileError && <small>{fileError}</small>}
    </div>
  </div>;
}

export function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}
