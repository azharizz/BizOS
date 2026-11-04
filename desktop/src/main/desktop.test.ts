import { describe, expect, it } from 'vitest'
import { checkApp, checkUrl, closeTarget, noteApp, notesHtml } from './desktop'

describe('desktop actions only accept safe input', () => {
  it('opens apps by plain name, never a path or a shell string', () => {
    expect(checkApp('Microsoft Excel')).toBe('Microsoft Excel')
    expect(checkApp('Numbers')).toBe('Numbers')
    for (const bad of ['/bin/sh', '../../evil', 'Excel; rm -rf ~', 'a'.repeat(80), '']) expect(() => checkApp(bad)).toThrow()
  })
  it('writes notes only into a new document of a known notes app', () => {
    expect(noteApp('notepad', 'darwin')).toBe('TextEdit')
    expect(noteApp('TextEdit', 'darwin')).toBe('TextEdit')
    expect(noteApp('Apple Notes', 'darwin')).toBe('Notes')
    expect(noteApp('', 'darwin')).toBe('TextEdit')
    expect(noteApp('notepad', 'win32')).toBe('Notepad')
    expect(() => noteApp('Terminal', 'darwin')).toThrow()
    expect(notesHtml('a <b> & c\nnext')).toBe('a &lt;b&gt; &amp; c<br>next')
  })
  it('closes apps by name, but never the system or BizOS itself', () => {
    expect(closeTarget('notepad', 'darwin')).toBe('TextEdit')
    expect(closeTarget('Microsoft Word', 'darwin')).toBe('Microsoft Word')
    for (const bad of ['Finder', 'Dock', 'System Settings', 'BizOS', 'Electron', 'loginwindow', 'rm -rf ~']) {
      expect(() => closeTarget(bad, 'darwin')).toThrow()
    }
  })
  it('opens only http(s) links', () => {
    expect(checkUrl('https://duckduckgo.com/?q=llm')).toBe('https://duckduckgo.com/?q=llm')
    for (const bad of ['file:///etc/passwd', 'javascript:alert(1)', 'smb://x', 'x-apple.systempreferences:']) expect(() => checkUrl(bad)).toThrow()
  })
})
