interface Props {
  title: string
  languageCode: string
}

function hashCode(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) {
    h = (h * 31 + s.charCodeAt(i)) | 0
  }
  return Math.abs(h)
}

export function LessonCover({ title, languageCode }: Props) {
  const hue = hashCode(title) % 360
  const bg = `hsl(${String(hue)} 70% 60%)`

  return (
    <div
      className="relative flex h-[140px] w-full items-center justify-center"
      style={{ backgroundColor: bg }}
    >
      <span className="text-3xl font-bold uppercase tracking-wider text-white/90">
        {languageCode.toUpperCase()}
      </span>
      <div className="absolute inset-0 bg-gradient-to-b from-transparent to-black/15" />
    </div>
  )
}
