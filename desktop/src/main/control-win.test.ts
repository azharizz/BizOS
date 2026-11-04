import { describe, expect, it } from 'vitest'
import { findShortcut, sendKeys } from './control-win'
import { controllable, parseElements } from './desktop'

describe('Windows app control (pure parts; the PowerShell side is untested on a real PC)', () => {
  it('maps keys and modifiers to SendKeys, with cmd meaning Ctrl', () => {
    expect(sendKeys('return')).toBe('{ENTER}')
    expect(sendKeys('down')).toBe('{DOWN}')
    expect(sendKeys('a', ['cmd'])).toBe('^a')
    expect(sendKeys('s', ['ctrl', 'shift'])).toBe('^+s')
    expect(sendKeys('tab', ['alt'])).toBe('%{TAB}')
    expect(() => sendKeys('rm -rf')).toThrow()
    expect(() => sendKeys('a', ['hyper'])).toThrow()
  })

  it('reads UI Automation control types like the macOS roles', () => {
    expect(parseElements('Button\tSave\nEdit\tFile name\nText\tReady\n')).toEqual([
      { ref: 0, role: 'button', name: 'Save' }, { ref: 1, role: 'text field', name: 'File name' }, { ref: 2, role: 'text', name: 'Ready' }])
  })

  it('runs only shortcuts that are in the BizOS Shortcuts folder, by exact name', () => {
    const files = ['Morning report.lnk', 'Backup.ps1', 'notes.txt', 'Open CRM.url']
    expect(findShortcut(files, 'morning report')).toBe('Morning report.lnk')
    expect(findShortcut(files, 'Backup')).toBe('Backup.ps1')
    expect(findShortcut(files, 'notes')).toBe(null) // not a runnable type
    expect(findShortcut(files, '..\\..\\Windows\\System32\\cmd')).toBe(null)
  })

  it('never operates Windows shells, the registry, Task Manager or Settings either', () => {
    for (const app of ['PowerShell', 'Command Prompt', 'cmd', 'Windows Terminal', 'Registry Editor', 'Task Manager', 'Control Panel', 'Settings'])
      expect(() => controllable(app)).toThrow(/won't operate/)
    expect(controllable('File Explorer')).toBe('File Explorer')
    expect(controllable('Finder')).toBe('Finder') // turned on: moving to Trash and Cmd+Delete still ask first
  })
})
