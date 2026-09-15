/* Static entrypoint: all managed engines share a lease; H3 takes exclusive lease.
 * FD deliberately survives exec so an engine crash/parent exit cannot unlock early. */
#include <sys/file.h>
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>
int main(int argc,char **argv) {
    if(argc<3){fprintf(stderr,"gpu-guard LOCK EXEC [ARGS...]\n");return 2;}
    int fd=open(argv[1],O_CREAT|O_RDWR,0666);
    if(fd<0||flock(fd,LOCK_SH|LOCK_NB)){perror("GPU mode reserved by video");return 75;}
    execvp(argv[2],argv+2);perror("engine exec failed");return 127;
}
