import type { VideoSource } from './api'

export function VideoSourceDetails({ source }: { source: VideoSource }) {
  const settings = source.parameters
  return (
    <details className="video-source-details">
      <summary>视频来源 · 候选帧 {source.position}</summary>
      <dl>
        <dt>原始视频</dt>
        <dd><a href={source.original_url} download>{source.filename}</a></dd>
        <dt>原视频 SHA-256</dt>
        <dd><code>{source.sha256}</code></dd>
        <dt>抽帧参数</dt>
        <dd>
          从 {settings.start_seconds} 秒开始，{settings.duration_seconds === null
            ? '取剩余区间'
            : `时长 ${settings.duration_seconds} 秒`}，{settings.fps} fps，
          最多 {settings.max_frames} 帧，长边最多 {settings.max_edge} 像素
        </dd>
        <dt>FFmpeg</dt>
        <dd>{source.ffmpeg_version}</dd>
      </dl>
    </details>
  )
}
