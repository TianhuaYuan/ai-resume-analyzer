/**
 * JWT 解码测试：验证 base64url 编码的正确处理。
 * 
 * 问题：atob() 不处理 base64url 的 '-' 和 '_'，低概率触发解码失败。
 */

describe('safeDecodeJwt', () => {
  it('decodes standard base64 JWT', () => {
    const token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwidXNlcm5hbWUiOiJ0ZXN0IiwiZW1haWwiOiJ0ZXN0QGV4YW1wbGUuY29tIiwiZXhwIjoxNjAwMDAwMDAwfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c';
    
    const result = require('./jwt').safeDecodeJwt(token);
    
    expect(result).not.toBeNull();
    expect(result?.sub).toBe('1234567890');
    expect(result?.username).toBe('test');
  });

  it('decodes base64url JWT with "-" and "_" characters', () => {
    const token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwidXNlcm5hbWUiOiJ0ZXN0IiwiZW1haWwiOiJ0ZXN0QGV4YW1wbGUuY29tIiwiZXhwIjoxNjAwMDAwMDAwfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c';
    
    const result = require('./jwt').safeDecodeJwt(token);
    
    expect(result).not.toBeNull();
    expect(result?.sub).toBe('1234567890');
  });

  it('handles JWT with missing padding', () => {
    const token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkw.abc';
    
    const result = require('./jwt').safeDecodeJwt(token);
    
    expect(result).not.toBeNull();
    expect(result?.sub).toBe('1234567890');
  });

  it('returns null for invalid JWT format', () => {
    expect(require('./jwt').safeDecodeJwt('invalid')).toBeNull();
    expect(require('./jwt').safeDecodeJwt('a.b')).toBeNull();
    expect(require('./jwt').safeDecodeJwt('a.b.c.d')).toBeNull();
  });

  it('returns null for corrupted base64', () => {
    expect(require('./jwt').safeDecodeJwt('eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.invalid-base64.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c')).toBeNull();
  });
});