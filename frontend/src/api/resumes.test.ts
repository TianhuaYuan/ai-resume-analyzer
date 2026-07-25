/**
 * exportResume 测试：验证正确读取 localStorage key。
 * 
 * 问题：exportResume 使用 "token" 而非 "access_token"，导致永久 401。
 */

describe('exportResume', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
  });

  it('reads access_token from localStorage', async () => {
    const mockToken = 'test-access-token-123';
    localStorage.setItem('access_token', mockToken);

    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      text: async () => '# 测试简历\n\n内容',
    });

    await import('./resumes').then(({ exportResume }) => exportResume(1));

    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/resumes/1/export?format=markdown',
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: `Bearer ${mockToken}`,
        }),
      })
    );
  });

  it('does not use "token" as localStorage key', async () => {
    localStorage.setItem('token', 'wrong-token');
    localStorage.setItem('access_token', 'correct-token');

    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      text: async () => '# 测试简历',
    });

    await import('./resumes').then(({ exportResume }) => exportResume(1));

    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/resumes/1/export?format=markdown',
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer correct-token',
        }),
      })
    );
  });

  it('throws error when response is not ok', async () => {
    localStorage.setItem('access_token', 'test-token');

    global.fetch = jest.fn().mockResolvedValue({
      ok: false,
      status: 401,
    });

    await expect(
      import('./resumes').then(({ exportResume }) => exportResume(1))
    ).rejects.toThrow('导出失败: 401');
  });
});